# Arquitectura objetivo — Mitefemme

Documento de diseño para la evolución del MVP actual (IRS → protobuf) al
entregable final del TFM: una orquesta de agentes multiproducto que genera RFQs
en protobuf, las valora con QuantLib en C++, y compara modelos de OpenAI y
Anthropic sobre métricas de extracción **y de impacto económico**.

Estado: propuesta para revisar con el tutor. Ninguna decisión aquí es
irreversible salvo las marcadas como *cimiento*.

---

## 1. Objetivo y alcance

### 1.1 Qué debe demostrar el trabajo

1. Que una orquesta de agentes LLM puede convertir lenguaje natural de mesa de
   trading en una representación estructurada, tipada y verificable (protobuf).
2. Que esa representación es **directamente ejecutable**: alimenta un motor de
   valoración real (QuantLib C++) sin traducción manual.
3. Que distintos modelos de frontera (OpenAI y Anthropic) rinden de forma
   medible y distinta en esa tarea, y que la diferencia se puede cuantificar no
   solo en aciertos de campo sino en **euros de error de valoración**.

El punto 3 es la aportación diferencial. Comparar exactitud de extracción es un
ejercicio ya visto en la literatura; medir la **consecuencia económica** de cada
error de extracción, propagándolo a través de un motor de pricing profesional,
no lo es. Es el eje sobre el que conviene articular la defensa.

### 1.2 Alcance de producto

| Producto | Estado | Rol en el estudio |
|---|---|---|
| Vanilla IRS | Existe | Producto principal. Curvas duales, calendario, convenciones. |
| FRA | A implementar | Control. Extracción sencilla; si un modelo falla aquí, falla en todo. |

El diseño deja el coste de añadir un tercer producto en: **una entrada de
registro + un skill + un modelo Pydantic + un validador + un `case` en el
dispatcher C++**. Nada del núcleo cambia. Si más adelante se decide ampliar
(cap/floor y swaption europea son los candidatos naturales, porque introducen
volatilidad y separan de verdad a los modelos), no hay refactor.

### 1.3 Fuera de alcance

Interfaz gráfica, ejecución/booking real, curvas construidas a partir de datos
de mercado en vivo, productos exóticos, y fine-tuning de modelos.

---

## 2. Principios de diseño

*Cimiento.* Estos cinco principios justifican casi todas las decisiones
posteriores; conviene poder defenderlos uno a uno.

1. **El protobuf es el contrato, no un formato de salida.** Todo lo que cruza
   una frontera del sistema (LLM → Python, Python → C++, C++ → Python) es un
   mensaje protobuf. No hay JSON como formato de intercambio en ningún punto.
   Esto da tipado, validación de esquema gratuita y compatibilidad Python/C++
   con un único fichero fuente.

2. **El LLM entiende lenguaje; no ensambla, no valida y no valora.** El modelo
   solo hace aquello para lo que no hay alternativa determinista: comprender el
   texto. El ensamblaje del RFQ, la validación de reglas y el pricing son código
   determinista y auditable. Esta separación es lo que hace el sistema
   defendible ante un tribunal: los errores del LLM quedan acotados y medidos.

3. **Añadir un producto no toca el núcleo.** Extensión por registro, no por
   modificación. Es una propiedad verificable: se puede medir el tamaño del diff
   al añadir el FRA y reportarlo como evidencia de que la arquitectura escala.

4. **Todo resultado publicado en la memoria debe ser reproducible.** Fecha de
   valoración fija, datos de mercado versionados en el repositorio, semillas y
   configuraciones registradas junto a cada medición. Un NPV que cambia según el
   día en que se ejecuta el script no vale para una tesis.

5. **Cada llamada a un modelo se mide.** Latencia, tokens, coste, y resultado.
   Sin instrumentación no hay capítulo de resultados.

---

## 3. Capa 1 — Esquema protobuf multiproducto

### 3.1 Problema actual

`protos/pricing.proto` tiene `RFQ.irs` como campo fijo. Con dos productos habría
que añadir `RFQ.fra` y comprobar en tiempo de ejecución cuál está presente: un
diseño que se degrada con cada producto nuevo y que no comunica exclusividad.

### 3.2 Diseño propuesto

Se parte el esquema en cinco ficheros con responsabilidades separadas:

```
protos/
  common.proto     Tipos compartidos: Date, DayCount, Frequency,
                   BusinessDayConvention, Calendar, CurveRef, Direction.
  products.proto   InterestRateSwap, ForwardRateAgreement.
  rfq.proto        RFQ { rfq_id, metadata, oneof product { ... } }
  market.proto     MarketDataSet, YieldCurve, Quote.
  pricing.proto    PricingRequest, PricingResponse, PricingResult, PricingError.
```

El corazón es el `oneof`:

```proto
message RFQ {
  string rfq_id = 1;
  RFQMetadata metadata = 2;
  oneof product {
    InterestRateSwap irs = 10;
    ForwardRateAgreement fra = 11;
  }
}
```

Tres ventajas concretas:

- La exclusividad mutua se expresa en el esquema, no en código de validación.
- Python obtiene `rfq.WhichOneof("product")` como discriminador fiable.
- C++ obtiene `rfq.product_case()`, un enum: un `switch` sobre él con
  `-Werror=switch` hace que **el compilador falle si añades un producto al proto
  y olvidas implementar su pricer**. La consistencia entre las dos mitades del
  sistema queda garantizada por el compilador, no por disciplina.

### 3.3 Tipado fuerte de convenciones

El MVP guarda `discount_curve` y `floating_index` como cadenas libres. Para
pricing eso no basta: QuantLib necesita convenciones concretas. Se promueven a
enums en `common.proto` (`DayCount`, `BusinessDayConvention`, `Frequency`,
`Calendar`), con un valor `*_UNSPECIFIED = 0` que significa «el prompt no lo
dijo».

Esto tiene una consecuencia metodológica importante y deliberada: **el enum
distingue «no dicho» de «dicho mal»**. Un modelo que rellena `day_count: ACT_360`
sin que el prompt lo mencione está alucinando una convención de mercado, y el
sistema lo detecta. Esa distinción alimenta directamente la métrica de
alucinación de la sección 8.

Las convenciones no especificadas se resuelven en el pricer mediante una tabla
de defaults de mercado explícita y documentada (`marketdata/conventions.textproto`),
nunca dentro del LLM. Así el «conocimiento de mercado» del sistema es auditable
y está en un fichero, no repartido en prompts.

### 3.4 Metadatos de trazabilidad

`RFQMetadata` lleva `generated_at`, `model_id`, `provider`, `run_id` y
`schema_version`. Sin esto no se puede reconstruir qué modelo produjo qué RFQ al
analizar resultados meses después.

---

## 4. Capa 2 — Registro de productos (Python)

### 4.1 Contrato

```python
@dataclass(frozen=True)
class ProductSpec:
    product_type: str            # "IRS", "FRA"
    display_name: str            # para el prompt del orquestador
    skill_path: str              # skills/irs_extraction_skill.md
    fields_model: type[BaseModel]
    proto_message: type          # products_pb2.InterestRateSwap
    rfq_oneof_field: str         # "irs"
    validator: Callable[[BaseModel], ValidationReport]

PRODUCT_REGISTRY: dict[str, ProductSpec] = {...}
```

### 4.2 Consecuencias

- **El prompt del orquestador se genera desde el registro.** Hoy
  `agents/orchestrator_agent.md` lista los productos a mano; se desincronizará
  en cuanto añadas el segundo. La lista de productos soportados pasa a ser una
  sección inyectada en tiempo de ejecución a partir de `PRODUCT_REGISTRY`. El
  fichero Markdown conserva el rol y las instrucciones; los productos los pone
  el código.
- `app_service.generate_rfq_from_prompt` deja de tener ramas por producto: hace
  `spec = PRODUCT_REGISTRY[product_type]` y opera sobre el spec.
- Los tests se parametrizan sobre el registro, así que un producto nuevo hereda
  la batería de tests estructurales automáticamente.

### 4.3 El tercer agente: de ceremonia a métrica

Situación actual: `app_service.py:78` exige que la salida del `rfq_proto_agent`
sea idéntica byte a byte a `fields_to_textproto(...)`. Si debe ser idéntica al
mapper determinista, el agente no aporta nada y solo añade un modo de fallo y un
coste. Un tribunal lo va a señalar.

Decisión propuesta: **el mapper determinista pasa a ser la verdad del sistema**
(es el que produce el RFQ que se valora), y el agente proto se conserva como
**sujeto de medida**. En cada ejecución se lanzan ambos y se registra si
coinciden. Eso convierte el tercer agente en un KPI —*fidelidad de
serialización*— que responde a una pregunta legítima e interesante: ¿puede un
LLM serializar correctamente a un esquema protobuf que se le proporciona, o
conviene siempre dejar el ensamblaje al código?

Es la mejor salida: el agente deja de ser decorativo, el sistema no depende de
él para funcionar, y genera un resultado publicable. En la memoria se defiende
como decisión de diseño consciente, no como un vestigio.

---

## 5. Capa 3 — Proveedores LLM

### 5.1 Interfaz

```python
class LLMProvider(Protocol):
    name: str  # "openai" | "anthropic"
    def complete(self, *, model: str, system: str, user: str,
                 max_tokens: int) -> Completion: ...

@dataclass(frozen=True)
class Completion:
    text: str
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int
    stop_reason: str
    raw_model_id: str
```

Los modelos se identifican con una cadena `proveedor:modelo`, de modo que el
evaluador acepta directamente:

```
python src/evaluate.py --models openai:gpt-4.1-mini anthropic:claude-opus-5
```

### 5.2 Diferencias reales entre proveedores que la capa debe absorber

Esto no es cosmético; son incompatibilidades que afectan al diseño experimental
y que hay que documentar en la memoria:

| Aspecto | OpenAI | Anthropic |
|---|---|---|
| Prompt de sistema | Mensaje con `role: "system"` | Parámetro `system` de primer nivel |
| `temperature` | Admitido (`0` para determinismo) | **Eliminado en los modelos actuales — devuelve 400** |
| Control de esfuerzo | — | `output_config: {effort: low…max}` |
| Razonamiento | — | `thinking: {type: "adaptive"}` |
| Uso de tokens | `prompt_tokens`, `completion_tokens`, `total_tokens` | `input_tokens`, `output_tokens`, `cache_read_input_tokens` — **no hay `total_tokens`** |

**Implicación metodológica de peso.** El diseño experimental del MVP asume que
`temperature=0` garantiza reproducibilidad. En los modelos Claude actuales ese
parámetro ya no existe, así que la premisa «ambos modelos en configuración
determinista» no se sostiene. La respuesta correcta no es buscar un parámetro
equivalente, sino cambiar el diseño: **cada caso se ejecuta N veces (propuesta:
N=5) y la variabilidad se mide en lugar de suponerse**. Se reporta media y
desviación por métrica, y la propia estabilidad pasa a ser un resultado
comparativo — plausiblemente uno de los más interesantes del trabajo, porque una
mesa de trading no puede usar un extractor que da respuestas distintas al mismo
prompt.

Configuración de partida para el estudio: Anthropic con `thinking` adaptativo y
`effort` explícito y fijo por experimento; OpenAI con `temperature=0`. Ambas
configuraciones se registran en la telemetría, y la comparación se presenta como
«cada modelo en su configuración de mínima varianza», no como una igualdad de
parámetros que no existe.

### 5.3 Caché de prompt

El prompt de sistema (agente + skill + esquema proto) es idéntico en todos los
casos de una misma tanda y ronda el orden de magnitud del mínimo cacheable
(~1024 tokens). Anthropic factura la lectura de caché a ~0,1× y OpenAI también
descuenta el prefijo cacheado. Como el coste es una métrica del estudio, la caché
**debe** activarse y registrarse por separado: si no, se compara el coste de un
modelo con caché contra otro sin ella y la conclusión económica es falsa.

Requisito de diseño: el prefijo estable va primero y el prompt del usuario al
final; nada volátil (timestamps, UUIDs) entra en el prefijo. Se verifica que
`cache_read_input_tokens > 0` en llamadas repetidas.

### 5.4 Coste

Los precios **no se codifican en el código fuente**: viven en
`config/model_costs.toml`, con precio de entrada, salida y lectura de caché por
millón de tokens, y una fecha de vigencia. Motivo práctico: las tarifas cambian
—Claude Sonnet 5 tiene precio promocional hasta 2026-08-31, por ejemplo— y una
memoria con precios incrustados en el código envejece mal y no es auditable. El
fichero de tarifas se cita en el anexo de la memoria.

---

## 6. Capa 4 — Puente C++ / QuantLib

*Cimiento.* Es la parte de mayor riesgo técnico y la que más valor aporta a la
defensa.

### 6.1 Contrato de proceso

Un ejecutable `pricer` que:

1. Lee un `PricingRequest` **serializado en binario** por `stdin`.
2. Escribe un `PricingResponse` serializado en binario por `stdout`.
3. Devuelve 0 siempre que haya podido emitir una respuesta bien formada,
   incluidos los fallos de valoración.

Los errores de negocio (curva inexistente, fechas incoherentes, bootstrap que no
converge) **no van a `stderr` ni al código de salida**: van dentro de
`PricingResponse.error` como datos estructurados con código y mensaje. Razón: un
fallo de valoración causado por una extracción defectuosa es un *resultado del
experimento*, y tiene que ser registrable y clasificable, no una excepción que se
pierde. `stderr` queda reservado para logs de diagnóstico.

```proto
message PricingResponse {
  oneof outcome {
    PricingResult result = 1;
    PricingError  error  = 2;
  }
  EngineInfo engine = 3;   // versión de QuantLib, build id, fecha de valoración
}

message PricingResult {
  double npv = 1;
  string npv_currency = 2;
  double fair_rate = 3;              // par swap rate (IRS) / par forward (FRA)
  double bpv = 4;                    // sensibilidad a 1bp
  repeated CashflowLine cashflows = 5;
}
```

`EngineInfo` con la versión de QuantLib es innegociable: sin ella los números de
la memoria no son reproducibles por un tercero.

### 6.2 Por qué subproceso y no gRPC

Se descarta gRPC deliberadamente, y conviene tener la justificación preparada: no
hay ciclo de vida de servicio que gestionar, ni puertos, ni arranque previo; el
binario se depura desde la línea de comandos (`pricer < req.bin > resp.bin`), lo
que hace cada valoración de la memoria reproducible de forma aislada; y el
protobuf ya aporta el contrato tipado, que es el 90% del valor de gRPC en este
caso. gRPC añadiría una dependencia pesada a cambio de una capacidad —
concurrencia en red — que el trabajo no necesita. Sigue siendo el camino natural
si el sistema evolucionase a servicio, y así se menciona en trabajo futuro.

### 6.3 Construcción

`vcpkg` en modo manifiesto + CMake:

```json
{ "name": "mitefemme-pricer",
  "dependencies": ["quantlib", "protobuf"] }
```

CMake genera las clases C++ desde los mismos `.proto` que usa Python
(`protobuf_generate`), de modo que **no existe posibilidad de divergencia de
esquema entre los dos lenguajes**: un único fichero fuente, dos compilaciones.

Riesgo asumido: `quantlib` arrastra Boost y la primera compilación en Windows es
lenta (una o dos horas de reloj, mayoritariamente desatendida). Es coste de una
sola vez y se mitiga cacheando el árbol de vcpkg.

### 6.4 Organización

```
pricer/
  CMakeLists.txt
  vcpkg.json
  src/main.cpp           lee stdin, despacha por product_case(), escribe stdout
  src/curve_builder.cpp  MarketDataSet -> QuantLib::YieldTermStructure
  src/conventions.cpp    enums proto -> tipos QuantLib (DayCounter, Calendar...)
  src/price_irs.cpp
  src/price_fra.cpp
  tests/                 casos con NPV esperado, independientes de Python
```

El dispatcher de `main.cpp` es un `switch` sobre `rfq.product_case()` compilado
con `-Werror=switch` (MSVC: `/we4062`), que es el mecanismo descrito en 3.2 para
que el compilador imponga la paridad producto↔pricer.

### 6.5 Cliente Python

`src/pricing/pricer_client.py` invoca el binario con `subprocess.run`, pasando
bytes y recibiendo bytes. Un único punto de contacto, sin dependencias nativas en
Python, y trivial de sustituir por un doble en los tests.

---

## 7. Capa 5 — Datos de mercado

Esta capa no existe hoy y es un requisito ineludible del pricing.

### 7.1 El problema

En el MVP, `discount_curve: "EUR-OIS"` es una **etiqueta**. QuantLib no puede
descontar con una etiqueta: necesita una estructura temporal construida a partir
de cotizaciones. Sin resolver esto, no hay valoración posible.

### 7.2 Solución

`MarketDataSet` en `market.proto`: un conjunto de curvas identificadas por el
mismo identificador que aparece en el RFQ, cada una con sus instrumentos
cotizados (depósitos, FRAs, swaps). Se versionan como *fixtures* en el
repositorio:

```
marketdata/
  EUR-2026-08-24.textproto     curvas EUR-OIS y EUR-EURIBOR-6M
  conventions.textproto        defaults de mercado por divisa/índice
```

El pricer arranca un `PiecewiseYieldCurve` por cada curva referenciada.

### 7.3 Dos propiedades que esto habilita

**Reproducibilidad.** La fecha de valoración es un campo de `PricingConfig`, fija
para todos los experimentos de la memoria. Los NPV publicados se pueden
reproducir dentro de un año.

**Detección de alucinación con consecuencia.** Si un modelo inventa
`forwarding_curve: "EUR-EURIBOR-3M"` cuando el prompt decía 6M, la curva no
existe en el fixture y el pricer devuelve `PricingError(CURVE_NOT_FOUND)`. La
alucinación deja de ser una discrepancia de cadena de texto y pasa a ser un **RFQ
no valorable**: exactamente lo que ocurriría en producción. Es el argumento más
fuerte del trabajo y sale gratis del diseño.

---

## 8. Capa 6 — Evaluación y métricas

### 8.1 Ampliación de la telemetría

Sobre el esquema existente en `src/evaluation/telemetry.py`:

`api_calls` añade: `provider`, `cached_input_tokens`, `cost_usd`, `config_json`
(effort/temperature realmente usados), `attempt`, `stop_reason`.

`evaluation_runs` añade: `provider`, `product_type`, `repetition`,
`proto_agent_fidelity`, `hallucinated_fields`, `priced_ok`, `npv`,
`npv_reference`, `npv_error_bp`, `cost_usd`.

Nota: Anthropic no devuelve `total_tokens`; se calcula en la capa de proveedor
para mantener la columna comparable entre ambos.

### 8.2 Métricas

**Nivel 1 — comprensión**

1. Acierto de clasificación de producto (matriz de confusión IRS/FRA/UNSUPPORTED).
2. Exactitud de extracción por campo. Desglosada por campo, no agregada: revela
   *qué* falla. La conversión de tipo de interés (2,75% → 0.0275) y las
   convenciones son los sospechosos habituales.
3. **Tasa de alucinación**: campos rellenados que el prompt no menciona. Se mide
   con los prompts incompletos y es donde más se separan los modelos. Métrica
   crítica en un contexto financiero, donde inventar una convención de mercado es
   peor que declararse incompetente.

**Nivel 2 — estructura**

4. Tasa de RFQs que superan la validación.
5. Fidelidad de serialización del agente proto (sección 4.3).

**Nivel 3 — consecuencia económica** *(la aportación del trabajo)*

6. Tasa de RFQs efectivamente valorables.
7. **Error de valoración**: `|NPV_modelo − NPV_referencia|`, normalizado en
   puntos básicos sobre el nocional para poder agregar entre productos. El NPV de
   referencia se obtiene valorando el RFQ dorado del caso.

   Esta métrica separa dos cosas que la exactitud de campo confunde: un error en
   `discount_curve` puede mover el NPV varios puntos básicos mientras que un error
   de formato en un identificador puede no moverlo nada. **No todos los errores de
   extracción cuestan lo mismo**, y ese es precisamente el punto que ninguna
   evaluación puramente textual puede capturar.

**Nivel 4 — operación**

8. Latencia p50 / p95 por agente y extremo a extremo.
9. Coste por RFQ y **coste por RFQ correcta** (la que importa: un modelo barato
   que falla la mitad de las veces no es barato).
10. Estabilidad entre repeticiones (sección 5.2).

### 8.3 Diseño experimental

Matriz completa: `{modelos} × {casos} × {repeticiones}`. Con 4 modelos, ~12 casos
y 5 repeticiones son 240 ejecuciones de tres agentes cada una: volumen
perfectamente manejable en coste y tiempo, y suficiente para reportar
desviaciones con sentido.

Los casos cubren tres familias: **completos** (extracción limpia),
**incompletos** (debe detectar que faltan términos y no inventarlos) y **ambiguos
o con ruido** (redacción de mesa real, con jerga y abreviaturas). La tercera
familia es la que produce las diferencias interesantes; las dos primeras
establecen el suelo y verifican el rechazo.

---

## 9. Estructura final del repositorio

```
rfq-agents/
  agents/                 orquestador, especialista, agente proto
  skills/                 irs_extraction_skill.md, fra_extraction_skill.md
  protos/                 common, products, rfq, market, pricing
  marketdata/             fixtures de curvas y convenciones
  config/                 model_costs.toml, experiments.toml
  src/
    app_service.py        orquestación, sin ramas por producto
    registry.py           PRODUCT_REGISTRY
    llm/                  base.py, openai_provider.py, anthropic_provider.py
    models/               modelos Pydantic por producto
    validation/           validadores por producto
    proto/                mapper determinista
    pricing/              pricer_client.py
    evaluation/           telemetry.py, metrics.py, report.py
  pricer/                 proyecto C++ (CMake + vcpkg + QuantLib)
  evaluation/cases/       casos dorados
  tests/
  docs/                   este documento
```

---

## 10. Plan por fases

Cada fase termina con los tests en verde y algo demostrable.

| # | Fase | Contenido | Riesgo |
|---|---|---|---|
| 0 | Higiene | Arreglar propiedad de git, `CLAUDE.md`, sacar `outputs/` y `.pytest_cache` del control de versiones | Nulo |
| 1 | Esquema y registro | Partir los protos, `oneof`, registro de productos, prompt del orquestador generado. Solo IRS. Tests verdes. | Bajo |
| 2 | Proveedores | `LLMProvider`, Anthropic + OpenAI, caché de prompt, coste, telemetría ampliada | Bajo |
| 3 | FRA | Segundo producto de punta a punta. **Se mide el diff** como evidencia de extensibilidad. | Bajo |
| 4 | Datos de mercado | `market.proto`, fixtures de curvas, convenciones | Medio |
| 5 | Pricer C++ | vcpkg + CMake + QuantLib, IRS y FRA, tests C++ propios | **Alto** |
| 6 | Métrica económica | Cliente Python, NPV de referencia, error en pb, evaluador ampliado | Medio |
| 7 | Experimentos | Matriz completa, repeticiones, informes y gráficas para la memoria | Bajo |

**Sugerencia de secuencia:** la fase 5 es la única con riesgo real de bloqueo.
Merece la pena hacer una prueba de concepto mínima de la cadena vcpkg + QuantLib
+ protobuf en paralelo a las fases 1–3 —un binario que valore un swap con datos
incrustados y no lea nada— para descubrir los problemas de toolchain pronto y no
al final. Si esa prueba se atasca más de dos o tres días, existe una salida:
QuantLib-Python usa exactamente la misma biblioteca C++ vía SWIG, así que el plan
B mantiene el motor de valoración y solo cambia cómo se invoca. Conviene tener
identificada esa salida aunque no se use.

---

## 11. Riesgos

| Riesgo | Impacto | Mitigación |
|---|---|---|
| Toolchain C++ en Windows (vcpkg, Boost, MSVC) | Bloqueo de la fase 5 | Prueba de concepto temprana y aislada; plan B con los bindings SWIG sobre la misma biblioteca |
| Solo dos productos, uno de ellos trivial | Comparación con poco poder discriminante | El registro deja la puerta abierta a un tercero sin refactor; los casos ambiguos aportan dificultad por otra vía |
| Coste de API de la matriz de experimentos | Presupuesto | Caché de prompt, modelos pequeños en las tandas de desarrollo, matriz completa solo en la ejecución final |
| Precios de modelos desactualizados en la memoria | Conclusión económica inválida | Tarifas en fichero de configuración con fecha de vigencia, citado en anexo |
| Deriva del esquema entre Python y C++ | Fallos silenciosos | Un único `.proto` compilado para ambos; `switch` exhaustivo con `-Werror` |

---

## 12. Decisiones descartadas

Documentadas porque un tribunal preguntará por ellas.

- **JSON como formato de intercambio.** Descartado: sin tipos, sin validación de
  esquema, y no compartible con C++ sin escribir un parser a mano.
- **gRPC entre Python y C++.** Descartado por sobredimensionado (sección 6.2).
- **Un solo agente monolítico.** Descartado: impide atribuir el fallo a una etapa
  concreta, que es el objeto del estudio.
- **Que el LLM elija convenciones de mercado no especificadas.** Descartado: el
  conocimiento de mercado va en un fichero auditable, no en pesos de un modelo.
  Además destruiría la métrica de alucinación.
- **Eliminar el tercer agente.** Descartado a favor de convertirlo en métrica
  (sección 4.3): elimina el problema de diseño y produce un resultado.
