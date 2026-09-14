# Estado actual del trabajo

Última actualización: **2026-09-14, 16:49** (Madrid).

Documento de retomada: qué está hecho, qué está a medias y cuál es el siguiente
paso. Si vuelves al proyecto después de un tiempo, empieza por aquí.

---

## Dónde está el proyecto

**Copia de trabajo (la que tiene Git):**
`C:\Users\mprietol\Documents\TFM Miguel\quant-agent-ensemble\rfq-agents`

**Intérprete** (el venv vive en la copia antigua, es correcto usarlo):
`C:\Users\mprietol\Documents\TFM Miguel\rfq-agents\.venv\Scripts\python.exe`

**Comandos:**

```powershell
cd "C:\Users\mprietol\Documents\TFM Miguel\quant-agent-ensemble\rfq-agents"
$py = "..\..\rfq-agents\.venv\Scripts\python.exe"

& $py -m pytest -q                                   # 16 tests
& $py src\evaluate.py --models gpt-4.1-mini          # lanza una tanda
& $py src\report.py                                  # informe de la última tanda
```

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
| Soporte de Anthropic | ❌ Pendiente (falta clave) |
| Comparación tres agentes frente a uno | ❌ Aplazado |
| QuantLib en C++ | ❌ Aplazado |

**16/16 tests pasan.**

---

## Último resultado válido: tanda 3

`20260914T124125Z`, `gpt-4.1-mini`, 14 casos, 1 repetición.

| Métrica | Resultado |
|---|---|
| Clasificación de producto | **14/14 (100 %)** |
| Estado de validación | **14/14 (100 %)** |
| RFQ exacta | **14/14 (100 %)** |
| Exactitud por campo | **100 %** |
| Campos alucinados | **0** |

Las cuatro familias al 100 %, incluida `jerga` (3/3).

Latencia mediana 5.855 ms, p95 8.621 ms. Coste 0,0342 USD por pasada.

⚠️ **La cifra de fidelidad del agente proto de esa tanda (0/7) NO es válida.**
Ver más abajo.

---

## Lo que está a medias

### El agente proto: arreglo aplicado, sin medir

El agente proto es el único que no funciona, y hasta ahora **la medición estaba
mal**, no el modelo:

1. Se le comparaba contra una RFQ que incluye los calendarios de pago, pero no se
   le pasaban esos calendarios. No podía coincidir nunca.
2. Sus instrucciones decían «the root message is `RFQ`», y el modelo escribía
   `RFQ { ... }`, que en formato de texto protobuf es inválido: el mensaje raíz
   es implícito.

**Arreglos aplicados hoy a las 14:58–15:00:**

- `src/llm_client.py` → `generate_proto_text` acepta y envía los calendarios.
- `src/app_service.py` → `_measure_proto_agent` los genera y los pasa.
- `agents/rfq_proto_agent.md` → instrucción explícita de no escribir el nombre
  del mensaje raíz, con ejemplo correcto e incorrecto, y regla de copiar los
  campos repetidos uno por línea.

**La tanda 3 se lanzó a las 14:41, antes de esos arreglos.** Se verificó por dos
vías: el `prompt_hash` del agente proto en esa tanda es `501782dae533`, idéntico
al de la tanda anterior, mientras que el fichero actual da `39ef285eb8c0`; y las
peticiones registradas contienen cero líneas `payment_dates`.

**Siguiente paso inmediato:** relanzar y mirar solo la sección de fidelidad del
agente proto. Cualquier resultado es publicable; lo que no lo era es el 0 %
anterior, que medía una imposibilidad.

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

## Tareas pendientes, por orden

1. **Relanzar** para medir el arreglo del agente proto.
2. **Aviso de `prompt_hash`** en `report.py` (ver riesgo 2).
3. **Repeticiones** (`--repetitions 5`) para estimar variabilidad. Ahora mismo
   todas las cifras son de una sola pasada.
4. **Verificar tarifas** en `config/model_costs.toml`. El informe avisa de que
   están sin verificar; no publicar costes hasta hacerlo.
5. **Comparar modelos**: `--models gpt-4.1-mini gpt-4.1`. Responde al punto del
   tutor sobre experimentos con varios LLM.
6. **Anthropic**: falta clave y falta la capa de proveedor.
7. **Aplazados, no cancelados:** comparación de tres agentes frente a uno
   (`ARQUITECTURA.md` §8.4) y QuantLib en C++.

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

## Bitácora de experimentos

`docs/REGISTRO_EXPERIMENTOS.md` recoge cada tanda con su configuración, su salida
literal y el diagnóstico de sus fallos. Las bases de datos se archivan en
`outputs/` con nombre versionado.
