# Hallazgos para la memoria

Resultados con valor argumental, separados del detalle de cada tanda. El
desarrollo completo de cada uno está en `REGISTRO_EXPERIMENTOS.md`; aquí queda la
tesis y la evidencia mínima que la sostiene.

---

## 1. Ningún proveedor expone la temperatura en su generación actual

**Verificado el 21/09/2026 contra las dos APIs.**

| Proveedor | Cómo la rechaza |
|---|---|
| OpenAI, `gpt-5.6-*` y `gpt-6-astra` | `BadRequestError` 400: *«Unsupported value: 'temperature' does not support 0.0 with this model. Only the default (1) value is supported.»* |
| Anthropic, SDK 1.7.0 | `TypeError: Messages.create() got an unexpected keyword argument 'temperature'` — el parámetro no existe, falla en Python antes de la llamada |

**Tres consecuencias que la memoria debe declarar:**

1. **El barrido de temperatura es imposible con los modelos disponibles.** No es
   una decisión de diseño ni una omisión: el parámetro no se puede fijar.
2. **La reproducibilidad no se puede apoyar en fijar la temperatura a cero.** Esto
   explica la variabilidad observada entre tandas con casos e instrucciones
   idénticos, y obliga a tratar cada tanda como una muestra y no como una medida
   exacta.
3. **Barrer temperatura y publicar costes son objetivos incompatibles hoy.**
   Exigiría volver a la generación `gpt-4.1`, cuyas tarifas ya no figuran en la
   página de precios del proveedor y por tanto no son citables.

**Cómo está implementado.** `providers.py` trata la temperatura como algo que el
proveedor puede rechazar, con una excepción propia, y el cliente reintenta sin
ella. La alternativa —una lista de modelos que la admiten— quedaría obsoleta con
cada lanzamiento.

---

## 2. La literalidad de un modelo es una propiedad que se paga

`gpt-5.6-sol` pasó de **19/23 (82,6 %) a 23/23 (100 %)** sin cambiar de modelo, de
temperatura ni de casos. El único cambio fue una frase de la instrucción del
orquestador, que declaraba fuera de alcance las consultas de *pricing* que no
fuesen una operación nueva —y una valoración es exactamente eso.

`sol` aplicó la instrucción al pie de la letra y rechazó cuatro valoraciones.
`luna` y `terra` la ignoraron y acertaron **por no hacerle caso**.

**La tesis:** un modelo más literal no tolera una especificación imprecisa. Con
instrucciones exactas rinde al máximo; con instrucciones contradictorias es el
primero en romperse, porque no las suple con sentido común. **Elegir un modelo más
capaz obliga a escribir mejor la instrucción, no permite descuidarla.**

Es lo contrario del consejo habitual, y está sostenido por una medición
controlada: mismos casos, mismo modelo, una frase de diferencia.

---

## 3. Un evaluador puede ser estable, reproducible y engañoso

Seis defectos de instrumentación a lo largo del trabajo produjeron cifras
internamente consistentes y falsas. En todos, **una diferencia de tratamiento
entre las dos ramas de una comparación se leyó como un fallo del modelo**:

| Defecto | Síntoma | Causa real |
|---|---|---|
| Guardarraíl ambiguo sobre índices a un día | 2 falsos negativos | `SOFR 3M` es la pata flotante de un vanilla, no un OIS |
| Calendarios no enviados al agente proto | `MISMATCH` sistemático | Se comparaba contra una referencia que sí los contenía |
| «The root message is `RFQ`» | `UNPARSEABLE` | En protobuf de texto el mensaje raíz es implícito |
| Diferencial por omisión aplicado solo en el mapeador | 1 alucinación por caso | El agente recibía una entrada distinta |
| Diferencial por omisión no aplicado al caso dorado | 1 alucinación por caso | Misma asimetría, en la otra rama |
| Caso de fechas contradictorias clasificado como producto no soportado | fallo del orquestador | Es un IRS legítimo con datos incoherentes |

**La tesis:** cuatro tandas consecutivas arrojaron 0 % de fidelidad de
serialización con plena consistencia interna. Ninguna cantidad de repeticiones ni
de intervalos de confianza lo habría revelado, porque el defecto no estaba en la
varianza sino en la referencia.

**Regla de trabajo derivada:** cuando una métrica muestra un fallo sistemático e
idéntico en todos los casos, sospechar del instrumento antes que del modelo.
Verificar que la tarea era resoluble con la información suministrada y que la
referencia de comparación era alcanzable.

---

## 4. Un modelo de lenguaje serializa protobuf anidado con fidelidad total

**Nueve mediciones: tres modelos por tres tandas, coincidencia byte a byte
siempre.** Incluido el caso con cuarenta campos repetidos entre las dos patas, y
resuelto también por el modelo más barato.

La pregunta que motivaba conservar el agente proto queda cerrada sin matices. Y la
decisión de mantener el mapeador determinista deja de apoyarse en la capacidad
para apoyarse en el coste: ese agente consume entre el **39 % y el 44 %** del
presupuesto de cada pasada para reproducir lo que una función determinista de
cuarenta líneas produce en microsegundos y sin coste.

---

## 5. El bucle de autocorrección solo aporta cuando la especificación es imprecisa

| Condición | Casos rescatados por el bucle |
|---|---|
| Instrucción ambigua | 3 |
| Instrucción corregida | **0** |

Con la instrucción corregida, `terra` y `sol` resolvieron los veintitrés casos en
la primera pasada. La única activación restante, en `luna`, **no logró corregir el
caso**: el error estaba en la clasificación de producto, y el bucle solo reintenta
la extracción.

**La tesis:** un sistema con especificación cuidada paga latencia por un mecanismo
que no llega a ejercitar. Su valor es una red de seguridad frente a instrucciones
imperfectas, no una mejora del rendimiento.

**Limitación de diseño a declarar:** el bucle corrige la extracción, no la
clasificación. Los falsos negativos del orquestador son exactamente el caso que no
puede rescatar.

---

## 6. La transición del LIBOR cambió la estructura del producto, no solo el índice

La convención USD que el trabajo asumía inicialmente —pata fija semestral 30/360
contra SOFR 3M trimestral— **no existe**. Es la estructura de
`USD_FIXED_6M_LIBOR_3M`, la convención de LIBOR, con el nombre SOFR sustituido
encima. USD LIBOR cesó el 30 de junio de 2023.

Un *swap* vanilla en dólares es hoy un **OIS**: ambas patas anuales en ACT/360, con
el tipo a un día capitalizado y **sin plazo de fijación**. Verificado en OpenGamma
Strata, constante `USD_FIXED_1Y_SOFR_OIS`.

**La tesis:** un esquema de datos diseñado sobre la intuición previa a 2023 modela
un instrumento que ya no se negocia. El campo `tenor` deja de ser universal, y esa
es la razón de que el esquema distinga `IBOR` de `OVERNIGHT_COMPOUNDED`.

Con detalle y citas en `CONVENCIONES_MERCADO.md`.

---

## 7. Comparación de modelos: el eje de coste es el único concluyente

| Modelo | Acierto | Coste/pasada | Coste/caso válido |
|---|---|---|---|
| `gpt-5.6-luna` | 22/23 · RFQ exacta 78,3 % | **0,0278 $** | **0,0013 $** |
| `gpt-5.6-terra` | **23/23 · 100 %** | 0,2353 $ | 0,0102 $ |
| `gpt-5.6-sol` | **23/23 · 100 %** | 0,4178 $ | 0,0182 $ |

**Recomendación: `terra`.** Empata con `sol` —cero pares discordantes en el
contraste pareado— y cuesta un 78 % menos.

**`luna` es defendible cuando el coste manda**, a costa de dos debilidades
concretas: un falso positivo de frontera de producto repetido en las tres tandas
(aceptó un *swap* en euros contra SOFR) y una aritmética de fechas que se degrada
—RFQ exacta del 95,5 % al 78,3 %— concentrada en los casos que exigen resolver
*spot* o una estructura diferida.

**Advertencia estadística:** ningún par alcanza potencia en el contraste de
McNemar, con uno, uno y cero pares discordantes frente a los seis que exige el
binomial exacto. **No debe redactarse como empate**: con veintitrés casos y una
repetición la comparación de acierto no tiene resolución. La de coste, que difiere
en un factor de veinte, sí es concluyente.

**El precio de `sol` es promocional** hasta el 21 de noviembre de 2026; citarlo
exige hacer constar esa condición.
