# Estado actual del trabajo

Última actualización: **2026-09-21, 09:45** (Madrid).

Documento de retomada: qué está hecho, qué está a medias y cuál es el siguiente
paso. Si vuelves al proyecto después de un tiempo, empieza por aquí.

---

## Dónde está el proyecto

**Copia de trabajo (la que tiene Git):**
`C:\Users\mprietol\Documents\TFM Miguel\quant-agent-ensemble\rfq-agents`

**Intérprete.** El venv sigue en la copia antigua del proyecto
(`C:\Users\mprietol\Documents\TFM Miguel\rfq-agents\.venv`, Python 3.13). Es una
fuente de confusión (dos copias, una sin Git) y ya ha causado una tanda medida
con instrucciones desactualizadas. Pendiente: crear el venv dentro de esta copia
con `python -m venv .venv; pip install -r requirements.lock` y retirar la antigua.
Mientras tanto:

```powershell
cd "C:\Users\mprietol\Documents\TFM Miguel\quant-agent-ensemble\rfq-agents"
$py = "..\..\rfq-agents\.venv\Scripts\python.exe"

& $py -m pytest -q                                   # tests
& $py src\evaluate.py --models gpt-4.1-mini          # lanza una tanda
& $py src\report.py                                  # informe de la última tanda
```

Requiere Python 3.11 o superior (`tomllib`). `requirements.lock` fija las
versiones exactas con las que se midieron las tandas.

El `.env` con la clave de OpenAI **no está en el repo** (correcto). Si falta:
`copy "..\..\rfq-agents\.env" .env`

---

## Qué está implementado

| Componente | Estado |
|---|---|
| Cadena de tres agentes: orquestador, especialista, proto | ✅ |
| Validación determinista con lista de términos a especificar | ✅ |
| Mapeador determinista a protobuf | ✅ |
| Esquema de IRS con dos patas y doble curva (Definición 2.19) | ✅ |
| Generación determinista de calendarios de pago | ✅ |
| 14 casos dorados en cuatro familias | ✅ |
| Comparación de campos aplanada (16 términos, no 10) | ✅ |
| Identificador de tanda (`batch_id`) en la telemetría | ✅ |
| Informe con desglose por familia | ✅ |
| Valores por omisión simétricos entre mapeador y agente | ✅ |
| Soporte de Anthropic | ❌ Pendiente (falta clave) |
| Comparación tres agentes frente a uno | ❌ Aplazado |
| QuantLib en C++ | ❌ Aplazado |

**Correcciones del 2026-09-15** (revisión del proyecto, sin relanzar tandas):

- El coste por llamada ahora descuenta los tokens de entrada servidos desde la
  caché de prompt de OpenAI (`prompt_tokens_details.cached_tokens`). Los costes
  de las tandas 1 a 4 se calcularon sin ese descuento y están **sobreestimados**;
  hay que relanzar antes de citar cifras de coste.
- El evaluador distingue una salida fuera de contrato del agente (`IRS.` en vez
  de `IRS`, o un `InterestRateSwap` no parseable) de un error de API. La primera
  cuenta como fallo del caso con producto `MALFORMED`; la segunda se excluye del
  agregado, como antes. Hasta hoy ambas se excluían.
- Las bases de datos archivadas están en `evaluation/results/`, bajo Git.
- `with_defaults` normaliza la frecuencia de pago a mayúsculas.
- README: Python 3.11+ y `requirements.lock`.

---

## Último resultado: tanda 4, todo al 100 %

`20260914T150109Z`, `gpt-4.1-mini`, 14 casos, 1 repetición.

| Métrica | Resultado | IC 95 % |
|---|---|---|
| Clasificación de producto | **14/14 (100 %)** | [78 %, 100 %] |
| Estado de validación | **14/14 (100 %)** | [78 %, 100 %] |
| RFQ exacta | **14/14 (100 %)** | [78 %, 100 %] |
| Exactitud por campo | **100 %** | — |
| Campos alucinados | **0** | — |
| Fidelidad del agente proto | **7/7 (100 %)** | [65 %, 100 %] |

Las cuatro familias al 100 %, incluida `jerga` (3/3).

Latencia mediana 6.729 ms, p95 18.626 ms. Coste 0,0395 USD por pasada, 0,0028 USD
por caso válido.

**El sistema completo funciona sin fallos.** No queda ninguna pregunta abierta
sobre su comportamiento; lo que falta es robustecer la evidencia (repeticiones,
más modelos) y verificar las tarifas.

---

## Cómo se llegó aquí: cuatro fallos, ninguno del modelo

Conviene saberlo para no repetirlo. Las tandas 1 a 3 registraron 0 % de fidelidad
del agente proto y dos falsos negativos de clasificación. **Nada de eso era del
modelo.** Eran cuatro defectos de instrumentación:

1. **Orquestador.** Declaraba no soportados los «*overnight index swaps*», y el
   modelo asimiló `SOFR 3M` y `SONIA 3M` a esa categoría. Son índices a un día
   con plazo declarado, es decir, la pata flotante de un vanilla.
2. **Calendarios no enviados.** El agente proto se comparaba contra una RFQ que
   incluye los calendarios de pago, sin recibirlos. Imposible coincidir.
3. **Instrucción del mensaje raíz.** Decía «the root message is `RFQ`»; el modelo
   escribía `RFQ { ... }`, inválido en formato de texto protobuf, donde el
   mensaje raíz es implícito.
4. **Valor por omisión asimétrico.** El diferencial ausente se rellenaba a cero
   dentro del mapeador, así que la referencia contenía `spread: 0.0` y al agente
   no se le enviaba ese término. Corregido con
   `validation.irs_validator.with_defaults`, que se aplica una sola vez antes de
   que los términos lleguen a cualquiera de los dos consumidores.

**Regla práctica:** antes de atribuir un fallo al modelo, verificar que la tarea
era resoluble con la información suministrada y que la referencia de comparación
es alcanzable. Cuatro tandas consecutivas dieron 0 % con plena consistencia
interna; ninguna cantidad de repeticiones lo habría revelado.

---

## Riesgo conocido: medir contra una versión que ya no existe

Ha ocurrido dos veces hoy, de dos formas distintas:

1. **Tandas mezcladas.** La base de datos acumula ejecuciones. Se relanzó sin
   archivar y el informe agregó dos tandas medidas contra casos dorados
   distintos, presentando como inestabilidad del modelo lo que era un cambio de
   referencia. *Mitigado:* existe `batch_id` y el informe usa por omisión la
   última tanda.
2. **Instrucciones desactualizadas.** Se lanzó una tanda antes de que los
   arreglos estuvieran en disco. *No mitigado:* la telemetría guarda
   `prompt_hash` por llamada, pero el informe no compara ese hash con el del
   fichero actual. **Mejora pendiente:** que `report.py` avise cuando una tanda
   se midió con instrucciones distintas de las presentes.

**Regla de trabajo mientras no esté mitigado:** después de editar un agente, un
*skill* o un caso dorado, relanzar antes de leer cualquier cifra.

---

## Rediseño acordado en la reunión del 2026-09-15

Las notas están en `../notas tutorias.txt` (fuera del repo). Cambian tres cosas de
fondo que **contradicen decisiones actuales** y hay que planificar antes de
seguir midiendo, porque invalidan los casos dorados:

1. **Esquema.** `forecast_curve` pasa dentro de `floating_leg`. Cada pata lleva su
   calendario de pagos completo y explícito, y **lo calcula el LLM**, no
   `schedule.py` (motivo: periodos rotos). Hoy el skill prohíbe al agente emitir
   `payment_dates`; habrá que invertirlo y medir la exactitud del calendario
   como un campo más. Nota: el ejemplo de la reunión excluye la fecha de inicio
   del vector (5 fechas fijas, 10 flotantes para 5 años); `schedule.py` hoy la
   incluye como T_0 (6 y 11).
2. **Obligatorios frente a convención.** Solo siete términos son impepinables
   (`rate`, `maturity_date`, `valuation_date`, `effective_date`, `currency`,
   `notional`, `is_fixed_rate_receiver`). El resto se deriva por convención de
   mercado documentada (EUR y USD, vencimiento > 1 año). Esto invierte el
   principio «nunca asumir» de `REQUIRED_TERMS`, del skill y de la familia
   `incompletos`: los casos `sin_bases_calculo`, `sin_curvas` y `sin_frecuencias`
   pasan a ser **válidos** y hay que añadir casos sin `rate`, sin `maturity`,
   sin divisa. Conviene mantener medible la distinción entre «extraído del
   texto» y «rellenado por convención» en la telemetría.
3. **Bucle acotado.** Guardarraíles de sanidad (fechas absurdas, negativos) y
   reintento vía orquestador con máximo 5 iteraciones. Hoy no hay bucle.

## Rediseño acordado con el tutor (15/09/2026, respuesta 21/09/2026)

Aprobado por él, pendiente de implementar. Detalle completo de convenciones en
`docs/CONVENCIONES_MERCADO.md`.

**Esquema**
- `forecast_curve` pasa dentro de `floating_leg`
- **Ambas patas** llevan vector de fechas de pago explícito
- Motivo: con periodos rotos el calendario no se deduce de (inicio, vencimiento,
  frecuencia). Los periodos rotos se piden en el *prompt*, no son automáticos
- **Las fechas las calcula el LLM** (él lo dejó a criterio propio)
- Mismo tipo para todos los periodos

**Campos**
- Obligatorios: `rate`, `maturity_date`, `valuation_date`, `effective_date`,
  `currency`, `notional`, `is_fixed_rate_receiver`
- Opcionales, derivables de convención: `day_count`, `payment_frequency`,
  `tenor`, `index`, curvas
- ⚠️ Esto **invierte** la regla actual de no rellenar nada. Afecta a la métrica de
  alucinación: habrá que distinguir «derivado de convención documentada» de
  «inventado»

**Arquitectura**
- Bucle acotado a **5 iteraciones**, no hasta el éxito
- Guardarraíles de sanidad: no fechas del año 1050, no negativos donde no procede
- Si no valida, vuelve al orquestador con el error
- Sin revisión humana. Contrato: entrada → error o RFQ bien conformada

**Alcance:** solo EUR y USD. GBP descartado.

### Bloqueante: los OIS pasan a ser producto soportado

Un *swap* vanilla USD **es** un OIS desde el cese del LIBOR. Decisión del
21/09/2026: aceptarlos. Implica reescribir la sección del orquestador que los
rechaza y que presupone un «SOFR 3M» inexistente, rehacer los casos dorados USD, y
decidir cómo modelar `tenor`, que es obligatorio en EUR y no aplica en USD.

---

## Tareas pendientes, por orden

0. **Planificar el rediseño anterior** y decidir qué casos dorados se reescriben.
   Relanzar la tanda 4 tras las correcciones de hoy para tener cifras de coste
   correctas del diseño actual antes de cambiarlo (sirve de línea base).
1. **Repeticiones** (`--repetitions 5`) para estimar variabilidad. Todas las
   cifras actuales son de una sola pasada, con intervalos anchos.
2. **Verificar tarifas** en `config/model_costs.toml`. El informe avisa de que
   están sin verificar; no publicar costes hasta hacerlo.
3. **Comparar modelos**: `--models gpt-4.1-mini gpt-4.1`. Responde al punto del
   tutor sobre experimentos con varios LLM.
4. **Aviso de `prompt_hash`** en `report.py` (ver riesgo 2 más abajo).
5. **Anthropic**: falta clave y falta la capa de proveedor.
6. **Aplazados, no cancelados:** comparación de tres agentes frente a uno
   (`ARQUITECTURA.md` §8.4) y QuantLib en C++.

### Decisión de diseño ya respaldada por datos

Con la fidelidad del agente proto resuelta en 7/7, la pregunta de si conservarlo
deja de ser sobre capacidad y pasa a ser económica: es el más lento de los tres
(9.415 ms de media frente a 2.856 ms del especialista), consume el **29 % del
coste** de cada pasada y produce el mismo mensaje que una función determinista
genera sin coste. Material directo para el capítulo de conclusiones.

---

## Sobre la memoria

Los cuatro capítulos LaTeX (modelo teórico, implementación, planificación,
presupuesto) están en `docs/latex/` en estado de **borrador generado**, no
revisado. Antes de usarlos hay que reescribirlos en voz propia y añadir citas: el
capítulo teórico expone teoría de otros autores sin citar a nadie.

Pendientes de la matriz de evaluación de la UC3M: bibliografía en APA, estado del
arte, resumen en inglés (obligatorio) y mención explícita de la URL del
repositorio.

**Referencia obligatoria**, que además fija el esquema del IRS:

> Ausín Amigo, M. (2025). *Quantitative Finance: Code, Concepts, and Practice: A
> Practitioner's Guide for Financial Engineers*. Universidad Carlos III de
> Madrid. ISBN 978-84-10132-25-2. https://hdl.handle.net/10016/48560

Definición 2.19 (pág. 59) para la estructura de patas, §2.4.6.2 para el marco de
doble curva, pág. 57 para las bases de cálculo, Código 2.11 (pág. 63) para los
nombres de campo y las simplificaciones adoptadas.

---

## Documentos del proyecto

| Fichero | Contenido |
|---|---|
| `ESTADO_ACTUAL.md` | Este documento: retomada y estado |
| `CONVENCIONES_MERCADO.md` | Convenciones EUR y USD verificadas, con fuentes |
| `REGISTRO_EXPERIMENTOS.md` | Bitácora de tandas con diagnóstico |
| `ARQUITECTURA.md` | Diseño objetivo, con tabla de qué está implementado |
| `FLUJO_AGENTES.md` | Flujo real con trazas de ejecución |
| `Overleaf/referencias.bib` | Bibliografía en formato biblatex |

---

## Bitácora de experimentos

`docs/REGISTRO_EXPERIMENTOS.md` recoge cada tanda con su configuración, su salida
literal y el diagnóstico de sus fallos. Las bases de datos se archivan en
`evaluation/results/` con nombre versionado y bajo Git; `outputs/evaluations.db`
es solo la copia de trabajo y no se versiona.
