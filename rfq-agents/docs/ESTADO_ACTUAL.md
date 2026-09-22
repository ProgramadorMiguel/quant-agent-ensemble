# Estado actual del trabajo

Última actualización: **2026-09-21, 16:50** (Madrid).

Documento de retomada. **Si vuelves al proyecto, o si abres una conversación nueva
para escribir la memoria, empieza por aquí.** Contiene lo que hace falta saber para
redactar los capítulos de resultados y conclusiones sin volver a mirar el código.

---

## 1. Qué es este trabajo

Un sistema que convierte una petición de cotización de *swap* de tipos de interés,
escrita en lenguaje natural por una mesa de negociación, en una **RFQ estructurada
en protobuf** lista para un motor de valoración.

**Tres agentes de lenguaje en cadena, más dos capas deterministas:**

```
Texto libre de la mesa
   ↓
1. ORQUESTADOR (LLM)     clasifica: IRS o UNSUPPORTED
   ↓
2. ESPECIALISTA (LLM)    extrae los términos, deriva las convenciones de
   ↓                     mercado y calcula los calendarios de pago
   VALIDADOR (Python)    ¿está completo y es coherente?
   ↓                     si no, devuelve el diagnóstico al paso 2 (máx. 5 pasadas)
3. MAPEADOR (Python)     escribe la RFQ que emite el sistema
   AGENTE PROTO (LLM)    hace lo mismo en paralelo, solo para medirse
```

**Contrato de salida, sin revisión humana:** o una RFQ bien conformada, o el motivo
por el que no se puede emitir.

**Alcance declarado:** EUR y USD, vencimientos de un año o más, convenciones
estándar salvo que la petición enuncie otra.

---

## 2. Dónde está y cómo se ejecuta

**Copia de trabajo, la que tiene Git:**
`C:\Users\mprietol\Documents\TFM Miguel\quant-agent-ensemble\rfq-agents`

**Repositorio público:** https://github.com/ProgramadorMiguel/quant-agent-ensemble
(mencionarlo en la memoria: lo pidió el tutor)

⚠️ **El venv vive en la copia antigua**, no en esta. Es una fuente real de
confusión y ya provocó una tanda medida con instrucciones desactualizadas.

```powershell
cd "C:\Users\mprietol\Documents\TFM Miguel\quant-agent-ensemble\rfq-agents"
$py = "..\..\rfq-agents\.venv\Scripts\python.exe"

& $py -m pytest -q                              # 84 tests
& $py tools\check_cases.py                      # verifica los 23 casos dorados
& $py src\runner.py                             # una petición a mano, interactivo
& $py src\evaluate.py --models gpt-5.6-terra    # una tanda completa
& $py src\report.py --all-batches               # el informe
```

El `.env` con las claves **no está en el repo** y nunca lo ha estado. Necesita
`OPENAI_API_KEY` y, para Claude, `ANTHROPIC_API_KEY`.

---

## 3. EL RESULTADO PRINCIPAL

Seis modelos, dos proveedores, **los mismos 23 casos y las mismas instrucciones**.

| Modelo | Proveedor | Acierto | Coste/caso válido | Latencia p50 |
|---|---|---|---|---|
| **`gpt-5.6-terra`** | OpenAI | **23/23** | **0,0102 $** | 9.011 ms |
| `gpt-5.6-sol` | OpenAI | **23/23** | 0,0182 $ | 11.029 ms |
| `claude-sonnet-5` | Anthropic | **23/23** | 0,0601 $ | 14.405 ms |
| `claude-opus-5` | Anthropic | **23/23** | 0,0904 $ | 15.252 ms |
| `gpt-5.6-luna` | OpenAI | 22/23 | **0,0013 $** | 7.153 ms |
| `claude-haiku-4-5` | Anthropic | 13/23 | 0,0203 $ | **3.475 ms** |

**Cuatro de los seis resuelven la tarea sin un solo fallo.** La elección de modelo
deja de ser de capacidad y pasa a ser económica.

**Recomendación: `gpt-5.6-terra`** — acierto perfecto al menor coste entre los que
lo logran. **`gpt-5.6-luna` cuando el coste manda**, un orden de magnitud más
barato, a cambio de un falso positivo de frontera de producto y una aritmética de
fechas poco fiable.

**Tarifas verificadas** el 21/09/2026 contra la documentación de cada proveedor,
salvo `gpt-4.1` y `gpt-4.1-mini`, que ya no figuran en la página de precios y no
deben citarse.

---

## 4. Los diez hallazgos para la memoria

**`docs/HALLAZGOS_MEMORIA.md` es el fichero que hay que abrir para redactar
resultados y conclusiones.** Cada hallazgo tiene su tesis y la evidencia mínima.
En resumen:

| | Hallazgo |
|---|---|
| 1 | Ningún proveedor expone la temperatura en su generación actual |
| 2 | La literalidad de un modelo es una propiedad que se paga |
| 3 | Un evaluador puede ser estable, reproducible y engañoso |
| 4 | Un LLM serializa protobuf anidado con fidelidad total |
| 5 | El bucle rescató 3 casos con instrucción ambigua y 0 con instrucción corregida |
| 6 | El cese del LIBOR cambió la estructura del producto, no solo el índice |
| 7 | El precio de lista no predice el coste de la tarea |
| 8 | Un modelo puede comprender la tarea y fallar el contrato de salida |
| 9 | Cuatro de seis modelos resuelven la tarea sin fallos |
| 10 | Dentro de OpenAI, solo el eje de coste es concluyente |

**Los tres más originales, y los que yo llevaría a las conclusiones:**

- **El 3.** **Siete** defectos de instrumentación produjeron cifras internamente
  consistentes y falsas. Cuatro tandas consecutivas dieron 0 % de fidelidad de
  serialización con plena coherencia, y ninguna cantidad de repeticiones lo habría
  revelado porque el defecto estaba en la referencia, no en la varianza.
- **El 2.** `gpt-5.6-sol` pasó de 82,6 % a 100 % arreglando una frase de una
  instrucción. Era el único modelo que la leía bien; los otros dos acertaban por
  ignorarla. Invierte el consejo habitual: un modelo más capaz obliga a escribir
  mejor la instrucción, no permite descuidarla.
- **El 7.** `claude-sonnet-5` y `gpt-5.6-terra` tienen tarifa casi idéntica y
  ambos aciertan 23/23, pero el primero cuesta cuatro veces más por pasada porque
  consume muchos más tokens. El precio por token no predice el coste de la tarea.

---

## 5. Los 23 casos de prueba

En `evaluation/cases/`, cinco familias. **Once los propuso el tutor**, doce son
propios. Los genera `tools/make_cases.py` a partir de sus términos económicos, no
están escritos a mano: una errata en un caso dorado se lee después como un fallo
del modelo, y eso ya ocurrió una vez.

| Familia | Casos | Qué mide |
|---|---|---|
| `cotizacion/` | 7 | Petición de precio, **sin tipo fijo**: es lo que se pregunta |
| `valoracion/` | 5 | *Swap* ya contratado, con su tipo, del que se pide el valor |
| `jerga/` | 3 | Taquigrafía de mesa: `Pay 5y 50m EURIBOR6M spot` |
| `no_valorables/` | 3 | Falta un término o los datos se contradicen |
| `no_soportados/` | 5 | Producto fuera de alcance |

Las capacidades que exigen: resolver *spot*, «el próximo lunes», la estructura
diferida `2Y1Y`, derivar el vencimiento de un plazo, deducir la divisa del índice,
leer la dirección de una intención de cobertura, periodos rotos, y convenciones no
estándar cuando la petición las enuncia.

---

## 6. Decisiones de diseño y su justificación

Material para el capítulo de implementación.

**El esquema sigue la Definición 2.19 del libro del tutor.** Dos patas, cada una
con su base de cálculo, frecuencia y calendario; dos curvas, la de descuento en el
nivel común y la de estimación **dentro de la pata flotante**, porque solo concierne
a esa pata. Los nombres de campo reproducen los argumentos de la clase `Swap` del
Código 2.11 para que la RFQ sea consumible por ese valorador sin traducción.

**`RFQPurpose` distingue cotización de valoración**, y la presencia del tipo fijo
es lo que las separa. En una cotización el tipo es lo que el cliente pregunta: el
motor lo resuelve haciendo cero el valor presente neto. Exigirlo convertía en
inválida la forma normal de pedir precio, y ninguno de los casos de mercado que
propuso el tutor lo enuncia.

**`FloatingRateType` distingue `IBOR` de `OVERNIGHT_COMPOUNDED`**, y el plazo de
fijación solo existe en el primero. Sin esa distinción no se puede modelar un
*swap* en dólares: tras el cese del LIBOR es un OIS contra SOFR capitalizado, sin
tenor.

**Los calendarios los calcula el agente, no Python.** Con periodos rotos el
calendario no se deduce de la frecuencia, y saber si un modelo de lenguaje lo
resuelve es una de las preguntas del trabajo.

**Las convenciones de mercado viven en Python para comprobarlas, no para
rellenarlas.** La derivación la hace el agente, que es lo que se mide; el validador
la contrasta y, si no coincide, el bucle corrige.

**El validador separa dos clases de problema.** Un término que la petición nunca
enunció se reclama y **no se reintenta**, porque la información no existe. Un error
del modelo alimenta el bucle. Sin esa distinción el bucle gastaría pasadas en lo
que no tiene arreglo.

---

## 7. Limitaciones que hay que declarar

No omitirlas: son lo que separa un TFM de un folleto.

- **Una repetición por modelo.** La estabilidad se infiere de la coincidencia entre
  tandas, no de repeticiones internas.
- **23 casos, doce escritos por el autor del sistema.** La comparación entre
  modelos usa los mismos casos y es válida; el nivel absoluto está sesgado.
- **El contraste de McNemar solo alcanza potencia en un par.** `haiku` frente a
  `opus` y a `sonnet` dan p = 0,002; los demás pares tienen menos de seis pares
  discordantes. **No redactarlo como empate**: es falta de resolución.
- **La temperatura no es un eje.** Ninguno de los dos proveedores la expone hoy, de
  modo que la variabilidad entre tandas es irreducible y la reproducibilidad no se
  puede apoyar en fijarla a cero.
- **El sistema no valora.** Estructura la petición; no calcula precio ni riesgo.
- **La detección de convenciones enunciadas es léxica**, sobre un vocabulario
  cerrado. No interpreta la frase.
- **El precio de `gpt-5.6-sol` es promocional** hasta el 21/11/2026.
- **Sin calendario de festivos ni fechas de fijación**, la misma simplificación que
  adopta el libro del tutor en la pág. 63.

---

## 8. La referencia obligatoria

El esquema se deriva del libro **del propio tutor**, y es cita obligada:

> Ausín Amigo, M. (2025). *Quantitative Finance: Code, Concepts, and Practice: A
> Practitioner's Guide for Financial Engineers*. Universidad Carlos III de Madrid.
> ISBN 978-84-10132-25-2. https://hdl.handle.net/10016/48560

| Dónde | Para qué |
|---|---|
| Definición 2.19, pág. 59 | Estructura de patas |
| §2.4.6.2 | Marco de doble curva |
| Pág. 57, ec. 2.27–2.28 | Bases de cálculo |
| Código 2.11, pág. 63 | Nombres de campo y simplificaciones adoptadas |
| Ec. 2.42 | Tipo par, lo que resuelve una cotización |

**`referencias.bib` tiene 24 entradas.** Las de convenciones y tarifas se añadieron
el 21/09: `opengamma2024conventions`, `opengamma2026strata`, `arrc2023closing`,
`quantlib2026`, `openai2026pricing`, `anthropic2026pricing`, `anthropic2026models`.

---

## 9. Documentos del proyecto

| Fichero | Para qué sirve al escribir |
|---|---|
| **`HALLAZGOS_MEMORIA.md`** | **Resultados y conclusiones.** Diez hallazgos con su tesis |
| `REGISTRO_EXPERIMENTOS.md` | Bitácora de las 17 tandas, con salidas literales y diagnóstico |
| `CONVENCIONES_MERCADO.md` | Convenciones EUR y USD verificadas, con fuentes citables |
| `ARQUITECTURA.md` | Diseño, con tabla de qué está implementado y qué no |
| `FLUJO_AGENTES.md` | Flujo real con trazas de ejecución |
| `ESTADO_ACTUAL.md` | Este documento |
| `Overleaf/referencias.bib` | Bibliografía, 24 entradas |
| `evaluation/results/*.db` | 13 bases archivadas: la evidencia reproducible |

Las bases de datos **se versionan a propósito**: sin ellas ninguna cifra de la
memoria sería reconstruible.

---

## 10. Qué queda

**El código está cerrado.** 84 tests, 23 casos verificados, seis modelos medidos.
No hacen falta más cambios para escribir la memoria.

**Lo que falta es la memoria**, y es donde está el riesgo:

| Pendiente | Estado |
|---|---|
| Estado del arte | `03_estado_arte.tex` existe; el tutor pidió «varias decenas» de referencias y hay 24 |
| Resumen en inglés | **Obligatorio por la matriz de la UC3M.** No existe |
| Plan de proyecto y análisis de costes | Borrador; el tutor los echaba en falta |
| Capítulo de resultados y conclusiones | Sin escribir. **Usar `HALLAZGOS_MEMORIA.md`** |
| URL del repositorio en el documento | Pendiente |
| Términos ingleses en cursiva | Pendiente de repasar |

⚠️ **Los capítulos LaTeX en borrador se generaron con asistencia.** Antes de
presentarlos hay que reescribirlos en voz propia y añadir citas: el capítulo teórico
expone teoría de otros autores sin citar a nadie, y eso es plagio independientemente
de quién redactó el texto.

**Aplazados, no cancelados:** comparación de tres agentes frente a uno
(`ARQUITECTURA.md` §8.4) y la integración de QuantLib en C++.
