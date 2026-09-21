# Registro de experimentos

Bitácora de las tandas de evaluación ejecutadas, con su configuración exacta, su
resultado literal y el diagnóstico de los fallos observados.

Se conserva porque el interés de una tanda no está solo en su tasa de acierto: el
contraste entre tandas con configuraciones distintas es lo que permite atribuir
un cambio de comportamiento a una causa concreta. Una tanda con fallos y causa
identificada aporta más al capítulo de resultados que una tanda limpia sin
explicación.

Las bases de datos completas de cada tanda se archivan en `evaluation/results/`,
que sí está bajo control de versiones (`outputs/` no lo está, y ahí solo vive la
base de datos activa). Cualquier cifra de esta bitácora es reconstruible con
`python src/report.py --db evaluation/results/<fichero>.db --batch <id>`.

| Fichero | Contenido |
|---|---|
| `evaluations_v2_conteo_10campos.db` | Tanda 1 (sin `batch_id`; comparador de 10 campos) |
| `evaluations_v3_mezcla_t2_t3.db` | Tandas 2 y 3 mezcladas, 28 filas sin `batch_id` |
| `evaluations_v4_t3_t4.db` | `20260914T124125Z` (tanda 3) y `20260914T144900Z` (relanzamiento con instrucciones aún no guardadas en disco, descartado) |
| `evaluations_v5_t4.db` | `20260914T150109Z` (tanda 4) |

---

## Tanda 1 — Guardarraíles agresivos: aparición de falsos negativos

| | |
|---|---|
| **Fecha** | 2026-09-14, 14:15 |
| **Modelo** | `gpt-4.1-mini` (proveedor OpenAI) |
| **Casos** | 14, en cuatro familias |
| **Repeticiones** | 1 |
| **Topología** | Cadena de tres agentes |
| **Esquema** | IRS con dos patas y doble curva |
| **Base de datos** | `evaluation/results/evaluations_v2_conteo_10campos.db` |

### Salida literal del evaluador

```
model            familia        case                   rep  campos    detalle                             ms
--------------------------------------------------------------------------------------------------------------
gpt-4.1-mini     completos      eur_payer_5y             1  10/10     match=10  proto:MISMATCH          9854
gpt-4.1-mini     completos      eur_payer_spread         1  10/10     match=10  proto:MISMATCH          6844
gpt-4.1-mini     completos      eur_receiver_3m          1  10/10     match=10  proto:MISMATCH          6714
gpt-4.1-mini     completos      gbp_receiver_sonia       1   0/10     missing=10                        1514
gpt-4.1-mini     completos      usd_payer_sofr           1  10/10     match=10  proto:MISMATCH          6096
gpt-4.1-mini     incompletos    sin_bases_calculo        1  10/10     match=10                          3484
gpt-4.1-mini     incompletos    sin_curvas               1  10/10     match=10                          2882
gpt-4.1-mini     incompletos    sin_fecha_valoracion     1  10/10     match=10                          3747
gpt-4.1-mini     incompletos    sin_frecuencias          1  10/10     match=10                          2968
gpt-4.1-mini     jerga          abreviado_eur_rec        1   9/10     match=9 wrong=1                   2963
gpt-4.1-mini     jerga          abreviado_usd            1   0/10     missing=10                         947
gpt-4.1-mini     jerga          bps_y_tenor              1  10/10     match=10  proto:MISMATCH          6519
gpt-4.1-mini     no_soportados  basis_swap               1   0/0                                        1286
gpt-4.1-mini     no_soportados  swaption                 1   0/0                                        1387
```

### Resultado agregado

| Métrica | Valor | IC 95 % |
|---|---|---|
| Clasificación de producto correcta | 12/14 (85,7 %) | [60 %, 96 %] |
| Estado de validación correcto | 11/14 (78,6 %) | [52 %, 92 %] |
| RFQ exacta | 11/14 (78,6 %) | [52 %, 92 %] |
| Exactitud por campo (macro-media) | 82,5 % | — |
| Campos alucinados | 0 | — |

### Resultado por familia

| Familia | Acierto | IC 95 % | Pregunta |
|---|---|---|---|
| `completos` | 4/5 (80,0 %) | [38 %, 96 %] | Extrae limpio una petición completa |
| `incompletos` | 4/4 (100 %) | [51 %, 100 %] | Detecta lo que falta y no lo inventa |
| `jerga` | 1/3 (33,3 %) | [6 %, 79 %] | Entiende la redacción abreviada de mesa |
| `no_soportados` | 2/2 (100 %) | [34 %, 100 %] | Rechaza un producto que no sabe tratar |

### Operación

| Magnitud | Valor |
|---|---|
| Latencia mediana extremo a extremo | 3.226 ms |
| Latencia percentil 95 | 7.897 ms |
| Coste de la pasada completa | 0,0265 USD |
| Coste por caso válido | 0,0024 USD |

Reparto por agente:

| Agente | Llamadas | ms medios | Tokens entrada | Tokens salida | Coste USD |
|---|---|---|---|---|---|
| `orchestrator` | 14 | 981 | 9.958 | 18 | 0,0040 |
| `product_specialist` | 10 | 2.283 | 39.566 | 1.342 | 0,0180 |
| `rfq_proto` | 5 | 3.114 | 7.559 | 919 | 0,0045 |

El desglose por agente contiene el dato que explica los fallos: el orquestador
recibió catorce peticiones y el especialista solo diez. Cuatro casos no llegaron
a la etapa de extracción. Dos son los de la familia `no_soportados`, donde el
rechazo es el comportamiento correcto. Los otros dos son fallos.

### Hallazgo principal: dos falsos negativos

Los casos `gbp_receiver_sonia` y `abreviado_usd` fueron clasificados
`UNSUPPORTED` por el orquestador siendo ambos *swaps* vanilla legítimos. El flujo
se detuvo en la primera etapa, de modo que no hubo extracción alguna: de ahí el
`missing=10` y las latencias anómalamente bajas de 1.514 ms y 947 ms, que
corresponden a una única llamada de clasificación.

Respuesta cruda del orquestador, recuperada de la telemetría:

```
--- orchestrator ---
PROMPT: RFQ for a GBP interest rate swap. Notional GBP 15,000,000, valuation
        date 2026-09-01, effective 2026-09-01, maturity 2028-09-01. The client
        receives fixed at 4.10% annually on ACT/...
RESPUESTA: 'UNSUPPORTED'

--- orchestrator ---
PROMPT: val 2026-09-01, 10mm USD from 2026-09-01 to 2031-09-01, pay 3,25% ann
        30/360 vs SOFR 3m qtr A/360 +15bp, disc USD-SOFR, fwd USD-SOFR-3M
RESPUESTA: 'UNSUPPORTED'
```

**Causa.** Las instrucciones del orquestador incluían entre los productos no
soportados la entrada «*overnight index swaps* cotizados como producto
separado». El modelo leyó «3M SONIA» y «SOFR 3m», identificó índices a un día, y
los asimiló a un OIS. Sin embargo, una pata flotante ligada a un tipo a un día
con un plazo declarado es precisamente la pata flotante de un *swap* vanilla
posterior a la desaparición del LIBOR: `SOFR 3M` denota el tipo a un día
capitalizado sobre períodos de tres meses. La instrucción era ambigua y el
modelo resolvió la ambigüedad hacia el rechazo.

Dos factores adicionales contribuyeron:

1. Una regla de resolución de ambigüedad redactada como «si el texto *podría no*
   ser un IRS vanilla, devuelve `UNSUPPORTED`; no concedas el beneficio de la
   duda», que sesga sistemáticamente hacia el rechazo.
2. En el caso `abreviado_usd`, la taquigrafía extrema de mesa se sumó a la duda
   sobre el índice. El caso `usd_payer_sofr`, con la misma estructura económica
   pero redactado en prosa completa, sí fue clasificado `IRS`. La redacción, y no
   solo el producto, estaba influyendo en la clasificación.

### Lectura metodológica

El resultado es relevante más allá del error concreto. Reforzar los
guardarraíles de un agente reduce la alucinación, que es el objetivo buscado,
pero introduce un modo de fallo simétrico y habitualmente no medido: el **falso
negativo**, es decir, rechazar una petición legítima que el sistema sabía tratar.

Esta tanda cuantifica ambos lados a la vez: **cero campos alucinados** y **dos
falsos negativos sobre doce peticiones válidas**. Un evaluador que solo midiera
alucinación habría registrado esta configuración como un éxito.

En un contexto de negociación los dos errores tienen coste, y no es el mismo: la
alucinación produce una RFQ valorable y equivocada, mientras que el falso
negativo devuelve negocio legítimo. La calibración del guardarraíl es, por tanto,
una decisión de diseño con una disyuntiva explícita, no un parámetro que convenga
maximizar.

### Fidelidad de serialización del agente proto

0/5 coincidencias con el mapeador determinista (`MISMATCH=5`, `NOT_RUN=9`). El
agente no reprodujo la estructura anidada de dos patas. No afecta al
funcionamiento del sistema, dado que la RFQ que se emite la produce siempre el
mapeador, pero es el primer dato sobre la capacidad del modelo de serializar
contra un esquema con submensajes. La tanda anterior, con el esquema plano de
diez campos, alcanzaba coincidencia completa.

### Correcciones aplicadas tras la tanda

1. **Orquestador.** Se añade una sección que declara explícitamente que un índice
   a un día con plazo declarado (`SOFR 3M`, `SONIA 3M`, `ESTR 6M`) es un IRS
   soportado, y que lo no soportado es un OIS solicitado como producto propio.
   Se sustituye la regla de duda por «rechaza por el producto, no por tu
   incertidumbre sobre la redacción», se declara que la taquigrafía nunca es
   motivo de rechazo, y se nombran ambos costes del error de clasificación.
   Tamaño de las instrucciones: 2.715 → 4.263 bytes.
2. **Comparador de campos.** `evaluation/metrics.py` aplana los submensajes en
   rutas con punto (`fixed_leg.day_count`). Sin aplanar, cada pata contaba como
   un único campo y un error dentro de ella se registraba como un solo fallo
   cualquiera que fuese el número de términos equivocados. Es el motivo por el
   que esta tanda muestra un denominador de 10 campos en lugar de 16.

### Limitaciones de esta tanda

- **El denominador de campos es 10, no 16.** Los términos de cada pata se
  contaron de forma agregada. Las cifras de exactitud por campo de esta tanda no
  son comparables con las posteriores y no deben publicarse como tales. Las de
  clasificación de producto y estado de validación sí lo son, porque no dependen
  del conteo de campos.
- **Una sola repetición por caso**, de modo que no hay estimación de la
  variabilidad entre ejecuciones.
- **Tarifas sin verificar** para `gpt-4.1-mini` en `config/model_costs.toml`. Las
  cifras de coste son orientativas.

---

## Tanda 2 — Guardarraíles calibrados: los falsos negativos desaparecen

| | |
|---|---|
| **Fecha** | 2026-09-14, 14:28 |
| **Modelo** | `gpt-4.1-mini` (proveedor OpenAI) |
| **Casos** | 14, en cuatro familias (los mismos de la tanda 1) |
| **Repeticiones** | 1 |
| **Cambio respecto a la tanda 1** | Orquestador con la ambigüedad del índice a un día resuelta; comparador de campos aplanado |
| **Base de datos** | `evaluation/results/evaluations_v3_mezcla_t2_t3.db` (sin `batch_id`, junto con la tanda 3) |

### Salida literal del evaluador

```
model            familia        case                   rep  campos    detalle                             ms
--------------------------------------------------------------------------------------------------------------
gpt-4.1-mini     completos      eur_payer_5y             1  16/16     match=16  proto:MISMATCH          7456
gpt-4.1-mini     completos      eur_payer_spread         1  16/16     match=16  proto:UNPARSEABLE       7409
gpt-4.1-mini     completos      eur_receiver_3m          1  16/16     match=16  proto:MISMATCH          7545
gpt-4.1-mini     completos      gbp_receiver_sonia       1  16/16     match=16  proto:MISMATCH          7808
gpt-4.1-mini     completos      usd_payer_sofr           1  16/16     match=16  proto:MISMATCH          7213
gpt-4.1-mini     incompletos    sin_bases_calculo        1  16/16     match=16                          3435
gpt-4.1-mini     incompletos    sin_curvas               1  16/16     match=16                          3917
gpt-4.1-mini     incompletos    sin_fecha_valoracion     1  16/16     match=16                          3040
gpt-4.1-mini     incompletos    sin_frecuencias          1  16/16     match=16                          4477
gpt-4.1-mini     jerga          abreviado_eur_rec        1  15/16     match=15 missing=1                3946
gpt-4.1-mini     jerga          abreviado_usd            1  16/16     match=16  proto:MISMATCH          7341
gpt-4.1-mini     jerga          bps_y_tenor              1  16/16     match=16  proto:MISMATCH          6312
gpt-4.1-mini     no_soportados  basis_swap               1   0/0                                         938
gpt-4.1-mini     no_soportados  swaption                 1   0/0                                         872
```

### Contraste con la tanda 1

| Métrica | Tanda 1 | Tanda 2 |
|---|---|---|
| Clasificación de producto correcta | 12/14 (85,7 %) | **14/14 (100 %)** |
| Falsos negativos | 2 | **0** |
| Campos alucinados | 0 | **0** |
| Términos por caso evaluados | 10 | **16** |
| Casos con extracción completa | 10/12 | **11/12** |

Los dos casos que la tanda 1 rechazaba, `gbp_receiver_sonia` y `abreviado_usd`,
pasan ambos a clasificarse `IRS` y extraen los dieciséis términos sin error. Sus
latencias suben de 1.514 y 947 ms a 7.808 y 7.341 ms, coherentes con recorrer las
tres etapas en lugar de detenerse en la primera.

**El resultado conjunto de las dos tandas es el hallazgo.** Corregir la
ambigüedad del guardarraíl elimina los falsos negativos **sin reintroducir
alucinación**: ambas tandas registran cero campos inventados. La disyuntiva entre
rechazar demasiado y aceptar demasiado no era, en este caso, una frontera
inevitable, sino el síntoma de una instrucción mal redactada. La lectura correcta
no es «hay que relajar los guardarraíles», sino «un guardarraíl ambiguo se
resuelve hacia el rechazo, y el coste de esa ambigüedad es medible».

### Resultado por familia

| Familia | Tanda 1 | Tanda 2 |
|---|---|---|
| `completos` | 4/5 (80,0 %) | **5/5 (100 %)** |
| `incompletos` | 4/4 (100 %) | **4/4 (100 %)** |
| `jerga` | 1/3 (33,3 %) | **2/3 (66,7 %)** |
| `no_soportados` | 2/2 (100 %) | **2/2 (100 %)** |

La familia `incompletos` mantiene el 100 % en las dos tandas: el sistema detecta
los términos ausentes y no los rellena con la convención de mercado habitual, que
es el comportamiento buscado.

### Caso `abreviado_eur_rec`: el caso dorado está mal especificado

Único fallo de campo de la tanda: `floating_leg.index: MISSING`.

El *prompt* del caso es:

```
valn dt 2026-09-01. EUR 250k, 2026-09-01 / 2028-09-01. rec fixed 2,05 pct ann
act/365 vs 6s semi act/360. disc EUR-ESTR fwd EUR-EURIBOR-6M
```

La pata flotante **no nombra el índice**. Solo declara el plazo, `vs 6s`. El
nombre EURIBOR aparece exclusivamente dentro del identificador de la curva de
estimación, `EUR-EURIBOR-6M`.

El caso dorado espera `index: "EURIBOR"`. Sin embargo, el *skill* de extracción
prohíbe explícitamente inferir el índice, y no autoriza deducirlo del nombre de
una curva. **El modelo omitió el campo obedeciendo la instrucción recibida.**

Se registra, por tanto, como un defecto del caso dorado y no del modelo. Es un
hallazgo metodológico por sí mismo: al construir una batería de casos con jerga
real es fácil escribir un *prompt* que el propio criterio del sistema declara
incompleto, y contabilizarlo como fallo del modelo introduce un sesgo en la
medición. La tanda 1 lo enmascaraba: allí el mismo caso aparecía como `wrong=1`
sin identificar el campo, porque el comparador agregaba la pata entera.

### Fidelidad de serialización del agente proto

| Estado | Casos |
|---|---|
| `MISMATCH` | 6 |
| `UNPARSEABLE` | 1 |
| `NOT_RUN` | 7 |

Coincidencia con el mapeador determinista: **0/7**. Con el esquema plano de diez
campos anterior, el mismo agente alcanzaba coincidencia completa; con la
estructura de dos patas no reproduce ni un caso, y en uno de ellos emite texto
que no es protobuf válido.

> **Nota añadida tras la tanda 4.** La lectura que aquí se hacía —«un modelo
> serializa bien contra un esquema plano y deja de hacerlo en cuanto hay
> submensajes anidados»— **es incorrecta y queda retirada**. La cifra de 0/14 de
> esta tanda no medía la capacidad del modelo sino tres defectos de la propia
> medición, detallados en la tanda 3 y corregidos antes de la tanda 4, que
> obtiene 7/7. Se conserva el texto original tachado para que la secuencia de
> diagnóstico quede trazable.

### Limitaciones de esta tanda

- **Una sola repetición** por caso, sin estimación de variabilidad.
- **Tarifas sin verificar** para `gpt-4.1-mini`.
- **El caso `abreviado_eur_rec` está pendiente de decisión**, según lo anterior:
  su tasa de la familia `jerga` no es publicable hasta resolverlo.

---

## Tanda 3 — El flujo completo sin un solo fallo

| | |
|---|---|
| **Identificador** | `20260914T124125Z` (2026-09-14, 14:41 Madrid) |
| **Modelo** | `gpt-4.1-mini` |
| **Casos** | 14, en cuatro familias |
| **Repeticiones** | 1 |
| **Cambio respecto a la tanda 2** | Caso dorado `abreviado_eur_rec` corregido; identificador de tanda introducido |
| **Base de datos** | `evaluation/results/evaluations_v4_t3_t4.db` |

### Resultado

| Métrica | Tanda 1 | Tanda 2 | Tanda 3 |
|---|---|---|---|
| Clasificación de producto | 12/14 | 14/14 | **14/14** |
| Estado de validación | 11/14 | 13/14 | **14/14** |
| RFQ exacta | 11/14 | 13/14 | **14/14** |
| Exactitud por campo | 82,5 % | 99,7 % | **100 %** |
| Campos alucinados | 0 | 0 | **0** |

| Familia | Tanda 1 | Tanda 2 | Tanda 3 |
|---|---|---|---|
| `completos` | 4/5 | 5/5 | **5/5** |
| `incompletos` | 4/4 | 4/4 | **4/4** |
| `jerga` | 1/3 | 2/3 | **3/3** |
| `no_soportados` | 2/2 | 2/2 | **2/2** |

Latencia mediana 5.855 ms, percentil 95 8.621 ms. Coste 0,0342 USD por pasada y
0,0024 USD por caso válido. Ningún fallo de campo registrado.

El caso `abreviado_eur_rec`, cuyo dorado se corrigió para no exigir un índice que
la petición no nombra, pasa a acierto: el modelo omite `floating_leg.index` y el
sistema lo reclama, que es el comportamiento correcto. La familia `jerga` alcanza
así 3/3.

### Corrección del caso dorado, y por qué cuenta

El caso esperaba `index: "EURIBOR"` aunque la petición solo declara `vs 6s`; el
nombre EURIBOR aparecía únicamente dentro del identificador de la curva
`EUR-EURIBOR-6M`. Se corrigió el dorado, no el *skill*: el caso pasa a medir si el
modelo resiste deducir el índice del nombre de una curva, que es una alucinación
plausible y un mejor uso del caso.

Este cambio de estado esperado, de `VALID` a `INVALID`, es el que provocó la
mezcla de tandas descrita más abajo.

### Incidencia 1: tandas agregadas sin distinguir

El informe de la tanda 3 se leyó inicialmente junto con las filas de la tanda 2,
porque la base de datos acumula ejecuciones y no se archivó antes de relanzar. El
agregado presentaba 13/14 y señalaba `abreviado_eur_rec` como inestable, «2
ejecuciones, 2 resultados distintos». No era inestabilidad del modelo: era el
mismo caso medido contra dos dorados diferentes.

**Mitigación aplicada.** Cada tanda recibe un `batch_id` y el informe usa por
omisión la última, con `--all-batches` para agregarlas explícitamente y un aviso
cuando se hace. Las cifras de la tanda 3 de este documento son las de la tanda
aislada, verificadas por consulta directa.

### Incidencia 2: la fidelidad del agente proto de esta tanda no es válida

La tanda registra 0/7 de coincidencia del agente proto (`MISMATCH=5`,
`UNPARSEABLE=2`). **La cifra no mide la capacidad del modelo**, por dos defectos
del propio diseño de la medición:

1. **La comparación era imposible de ganar.** El agente se comparaba contra la
   RFQ del mapeador, que incluye los calendarios de pago de cada pata, pero la
   petición que se le enviaba no contenía ni una fecha. Se verificó contando las
   apariciones de `payment_dates` en las peticiones registradas: cero.
2. **La instrucción inducía el fallo.** Decía «the root message is `RFQ`», y el
   modelo escribía `RFQ { ... }`. En formato de texto protobuf el mensaje raíz es
   implícito y nombrarlo produce `ParseError: Message type "pricing.RFQ" has no
   field named "RFQ"`. Los dos `UNPARSEABLE` de la tanda son exactamente eso.

Es la misma clase de error que el del orquestador en la tanda 1: **una
instrucción ambigua o incompleta produce un fallo que se atribuye al modelo.** En
los tres casos el contenido financiero era correcto; lo que falló fue lo que se
le pidió.

> **Nota añadida tras la tanda 4.** La conclusión que este documento sostenía en
> su primera redacción, «un modelo de lenguaje comprende la economía del producto
> mejor de lo que respeta la sintaxis del formato», **es falsa** y queda
> retirada. La tanda 4, con la medición corregida, obtiene 7/7 de fidelidad byte
> a byte. El modelo respetaba la sintaxis desde el principio; lo que fallaba era
> la medición.

Conviene señalar que el agente proto no afecta al funcionamiento del sistema. La
RFQ que se emite la produce siempre el mapeador determinista, y las 26 RFQ
escritas en `outputs/` son correctas.

**Arreglos aplicados** (14:58–15:00, posteriores a esta tanda):
`llm_client.py` envía los calendarios, `app_service.py` los genera y los pasa, y
`rfq_proto_agent.md` prohíbe explícitamente nombrar el mensaje raíz, con ejemplo
contrastado, y detalla cómo emitir campos repetidos.

### Limitaciones

- **Una sola repetición.** Sin estimación de variabilidad. Un 100 % sobre catorce
  casos y una pasada tiene un intervalo de Wilson de [78 %, 100 %]: es un buen
  resultado, no una garantía.
- **Tarifas sin verificar** para `gpt-4.1-mini`.
- **La fidelidad del agente proto queda sin medir**, por lo anterior.

---

## Tanda 4 — Medición corregida: el sistema completo sin fallos

| | |
|---|---|
| **Identificador** | `20260914T150109Z` (2026-09-14, 17:01 Madrid) |
| **Modelo** | `gpt-4.1-mini` |
| **Casos** | 14, en cuatro familias |
| **Repeticiones** | 1 |
| **Cambio respecto a la tanda 3** | Los tres defectos de medición del agente proto, corregidos |
| **Hash de instrucciones del agente proto** | `39ef285eb8c0` (la tanda 3 usó `501782dae533`) |
| **Base de datos** | `evaluation/results/evaluations_v5_t4.db` |

### Resultado

| Métrica | Resultado | IC 95 % |
|---|---|---|
| Clasificación de producto | **14/14 (100 %)** | [78 %, 100 %] |
| Estado de validación | **14/14 (100 %)** | [78 %, 100 %] |
| RFQ exacta | **14/14 (100 %)** | [78 %, 100 %] |
| Exactitud por campo | **100 %** | — |
| Campos alucinados | **0** | — |
| **Fidelidad del agente proto** | **7/7 (100 %)** | [65 %, 100 %] |

Las cuatro familias al 100 %. Ningún fallo de campo registrado.

### Progresión de las cuatro tandas

| Métrica | Tanda 1 | Tanda 2 | Tanda 3 | Tanda 4 |
|---|---|---|---|---|
| Clasificación de producto | 12/14 | 14/14 | 14/14 | **14/14** |
| Estado de validación | 11/14 | 13/14 | 14/14 | **14/14** |
| Exactitud por campo | 82,5 % | 99,7 % | 100 % | **100 %** |
| Campos alucinados | 0 | 0 | 0 | **0** |
| Fidelidad del agente proto | 0/5 | 0/14 | 0/7 | **7/7** |

### El hallazgo central: cuatro fallos, ninguno del modelo

La fidelidad del agente proto pasó de 0 % a 100 % **sin cambiar de modelo, de
temperatura ni de esquema**. Los cuatro registros de 0 % de las tandas anteriores
no medían la capacidad de `gpt-4.1-mini`: medían tres defectos encadenados en la
instrumentación, más un cuarto en el orquestador que afectaba a la clasificación.

| Defecto | Síntoma observado | Causa real |
|---|---|---|
| El orquestador declaraba no soportados los «*overnight index swaps*» | Dos IRS vanilla rechazados como `UNSUPPORTED` | `SOFR 3M` y `SONIA 3M` son índices a un día con plazo: pata flotante de un vanilla, no un OIS |
| La petición al agente proto no incluía los calendarios de pago | `MISMATCH` sistemático | Se comparaba contra una referencia que sí los contiene: imposible coincidir |
| La instrucción decía «the root message is `RFQ`» | `UNPARSEABLE` | En formato de texto protobuf el mensaje raíz es implícito; nombrarlo lo invalida |
| El valor por omisión del diferencial se aplicaba dentro del mapeador | `MISMATCH` de una sola línea, `spread: 0.0` | El agente recibía una entrada distinta de la del mapeador |

En los cuatro casos **el contenido financiero producido por el modelo era
correcto**. El último es el más ilustrativo: el diferencial ausente se rellenaba a
cero dentro del mapeador, de modo que la referencia contenía `spread: 0.0`
mientras que al agente no se le enviaba ese término. El modelo omitía un campo que
nunca recibió, que es el comportamiento correcto, y la comparación lo contaba como
error. Corregido aplicando el valor por omisión una sola vez, en
`validation.irs_validator.with_defaults`, antes de que los términos lleguen a
cualquiera de los dos consumidores.

**Lectura metodológica.** Es el resultado más transferible del trabajo. Un
evaluador automático de agentes puede producir cifras estables, reproducibles y
completamente engañosas: cuatro tandas consecutivas arrojaron 0 % de fidelidad con
plena consistencia interna. Ninguna cantidad de repeticiones ni de intervalos de
confianza habría revelado el problema, porque el defecto no estaba en la varianza
sino en la referencia. Antes de atribuir un fallo al modelo hay que verificar que
la tarea era resoluble con la información suministrada y que la referencia de
comparación es alcanzable.

### El coste del agente proto, ahora que se puede medir

| Agente | Llamadas | ms medios | Tokens salida | Coste USD | % del coste |
|---|---|---|---|---|---|
| `orchestrator` | 14 | 959 | 16 | 0,0063 | 16 % |
| `product_specialist` | 12 | 2.856 | 1.630 | 0,0216 | 55 % |
| `rfq_proto` | 7 | **9.415** | 3.716 | 0,0116 | **29 %** |

Con la fidelidad resuelta, la pregunta de diseño queda planteada en términos
económicos y no de capacidad: el agente proto **es el más lento de los tres**, con
9.415 ms de media frente a 2.856 ms del especialista, consume el **29 % del
presupuesto** de cada pasada, y produce exactamente el mismo mensaje que una
función determinista de cuarenta líneas produce en microsegundos y sin coste.

La latencia extremo a extremo lo refleja: el percentil 95 sube de 8.621 ms en la
tanda 3 a **18.626 ms**, y el caso `usd_payer_sofr`, con sesenta y dos campos
repetidos entre las dos patas, tarda 19,8 s. El coste por caso válido pasa de
0,0024 a 0,0028 USD.

La conclusión no es que un modelo de lenguaje no sepa serializar contra un esquema
anidado: **sabe hacerlo con fidelidad total, incluidos sesenta y dos campos
repetidos en orden**. Es que hacerlo no compensa cuando existe una alternativa
determinista, y esa afirmación queda ahora respaldada por una medición en lugar de
por una intuición de diseño.

### Limitaciones

- **Una sola repetición.** Un 100 % sobre catorce casos y una pasada tiene un
  intervalo de Wilson de [78 %, 100 %]: es un buen resultado, no una garantía. La
  fidelidad de 7/7 tiene un intervalo aún más ancho, [65 %, 100 %].
- **Un solo modelo y un solo proveedor.**
- **Tarifas sin verificar** en `config/model_costs.toml`.
- **Catorce casos** es una batería pequeña para afirmaciones generales.

---

## Tanda 5 — Pendiente

1. Repeticiones (`--repetitions 5`) para estimar variabilidad y estabilidad.
2. Verificar las tarifas antes de publicar cualquier cifra de coste.
3. Comparar `gpt-4.1-mini` con `gpt-4.1`, con contraste de McNemar.

Mejora pendiente en la instrumentación, derivada de la incidencia 2 de la tanda 3:
que `report.py` avise cuando el `prompt_hash` de una tanda no coincide con el del
fichero de instrucciones presente en disco.
