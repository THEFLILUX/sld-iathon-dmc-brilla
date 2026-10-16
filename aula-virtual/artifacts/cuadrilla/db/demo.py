"""DEMO_MODE data: fictional accounts, two courses ('Python para Análisis de Datos' and
'Especialización en Big Data') with their malla and, on request, classes with handwritten
challenges and simulated practice.

Everything is idempotent and goes through the same services as real data. No OpenAI call is needed.
Run explicitly with:  python -m db.demo
"""

from datetime import date, timedelta

from sqlalchemy import select, update

from ai import privacy
from ai.anonymize import anonimizar
from ai.schemas import RetoGenerado
from auth.passwords import hash_password
from config import settings
from db.models import (
    AgendaRepaso, Clase, ClaseTema, Curso, Inscripcion, Intento, Mensaje, Quiz, RetoVersion, Tema, Usuario,
)
from rules.calendar import ahora

CURSO = "Python para Análisis de Datos"
ADMIN = ("10000001", "Admin", "DMC", "admin")
DOCENTE = ("20000001", "Fernanda", "Ríos", "docente")
CURSO_BD = "Especialización en Big Data"
DOCENTE_BD = ("20000002", "Ricardo", "Paredes", "docente")
ALUMNOS_BD = ("70000001", "70000002", "70000003", "70000004")
ALUMNOS = (
    ("70000001", "Lucía", "Torres"), ("70000002", "Diego", "Ramírez"), ("70000003", "Valeria", "Quispe"),
    ("70000004", "Andrés", "Salazar"), ("70000005", "Camila", "Rojas"), ("70000006", "Mateo", "Huamán"),
)
RUBRICA_AUTOMATIZACION = [
    {"criterio": "Carga de datos", "descripcion": "Parte del archivo de origen y lo carga con pandas."},
    {"criterio": "Gráficos reutilizables", "descripcion": "Genera los gráficos con parámetros que se cambian sin reescribir el código."},
    {"criterio": "Exportación automática", "descripcion": "Lleva los gráficos al reporte final (por ejemplo, PowerPoint) sin pasos manuales."},
    {"criterio": "Mantenimiento", "descripcion": "Indica qué parámetros cambian en cada ejecución (mes, región, títulos)."},
]
MALLA = (
    # modulo, tema, objetivo, nivel_maximo, fundamental
    ("Fundamentos de analítica con Python", "Etapas de la analítica de datos",
     "Explicar las etapas de extraer, limpiar y procesar, analizar y visualizar datos.", "avanzado", True),
    ("Fundamentos de analítica con Python", "Entorno Google Colab",
     "Usar Google Colab para escribir y ejecutar código Python sin instalar nada.", "intermedio", False),
    ("Fundamentos de analítica con Python", "Librerías de Python y pandas",
     "Reconocer qué es una librería y para qué sirve pandas en el análisis de datos.", "avanzado", True),
    ("Datos con pandas", "Carga de datos desde Excel",
     "Cargar un archivo de Excel en un DataFrame con pandas y verificar sus columnas.", "avanzado", True),
    ("Datos con pandas", "Resúmenes y agrupaciones",
     "Resumir datos por categoría, como una tabla dinámica, usando agrupaciones.", "avanzado", False),
    ("Datos con pandas", "Limpieza y transformación de datos",
     "Completar datos faltantes, crear columnas nuevas y unir tablas antes de analizar.", "avanzado", True),
    ("Visualización y automatización", "Gráficos con seaborn",
     "Generar gráficos de columnas y circulares identificando ejes, valores, etiquetas y título.", "avanzado", False),
    ("Visualización y automatización", "Automatización de reportes",
     "Diseñar un flujo que lleve gráficos a un reporte de forma automática con bloques de código reutilizables.",
     "maestria", False),
    ("Visualización y automatización", "IA como apoyo para programar",
     "Pedir a la IA bloques de código y adaptarlos cambiando sus parámetros.", "avanzado", False),
    ("Visualización y automatización", "Python frente a Power BI",
     "Distinguir cuándo conviene generar gráficos con Python y cuándo un dashboard de Power BI.", "intermedio", False),
)


def V(tipo, enunciado, explicacion, pistas, *, opciones=(), correcta="", aceptadas=(), puntos=()):
    return {"tipo": tipo, "enunciado": enunciado, "explicacion": explicacion, "pistas": list(pistas),
            "opciones": list(opciones), "respuesta_correcta": correcta or (aceptadas[0] if aceptadas else ""),
            "respuestas_aceptadas": list(aceptadas), "puntos_clave": list(puntos), "casos_de_prueba": []}


CLASE_1 = [
    ("Etapas de la analítica de datos", 1, "Construir el gráfico antes de limpiar y procesar los datos.",
     "Lo primero que debemos hacer es traer data. Si no, ¿con qué construyo mi gráfica?", {
         "basico": V("alternativas", "Según la clase, ¿cuál es la primera etapa de la analítica de datos?",
                     "Sin data no se construye ninguna gráfica ni dashboard: primero se extrae, luego se limpia, se analiza y se visualiza.",
                     ["Piensa en qué necesitas antes de construir cualquier gráfica.",
                      "Sin esto, el docente dijo que «no hago nada».",
                      "Es la etapa de traer o extraer los datos."],
                     opciones=["Extraer (traer) los datos", "Construir el dashboard", "Limpiar los datos",
                               "Presentar el informe"], correcta="Extraer (traer) los datos"),
         "intermedio": V("alternativas",
                         "Te envían una base con la fecha de nacimiento de los trabajadores, pero tu dashboard necesita el promedio de edad. ¿En qué etapa trabajas y qué haces?",
                         "Es procesamiento: la data no siempre está lista; aquí se crea un dato nuevo (la edad) a partir de otro.",
                         ["La data que te llegó no está lista para el indicador que necesitas.",
                          "Hay que crear un dato que no viene en la base.",
                          "En la clase: «me mandaron fecha de nacimiento, pero yo necesito la edad»."],
                         opciones=["En la limpieza y procesamiento: calculas la edad como una columna nueva",
                                   "En la visualización: cambias el título del gráfico",
                                   "En la extracción: vuelves a pedir toda la base",
                                   "En el dashboard: promedias las fechas directamente"],
                         correcta="En la limpieza y procesamiento: calculas la edad como una columna nueva"),
         "avanzado": V("caso",
                       "Un compañero arma el gráfico de ventas por ciudad con la data recién descargada y el total sale mayor al real porque hay filas repetidas. ¿Qué etapa se saltó y cómo lo corregirías antes de graficar?",
                       "La limpieza va antes del análisis y la visualización: datos repetidos o incorrectos distorsionan cualquier resumen.",
                       ["Revisa el orden de las etapas que vimos.", "El problema está en la calidad de la data.",
                        "Se saltó la limpieza: hay que quitar duplicados antes de resumir."],
                       puntos=["Identifica que se saltó la etapa de limpieza o procesamiento",
                               "Propone revisar y eliminar las filas duplicadas antes de resumir",
                               "Indica que recién después se analiza y se genera el gráfico"],
                       correcta="Se saltó la limpieza. Primero eliminaría las filas repetidas y verificaría los datos; luego resumiría por ciudad y recién ahí graficaría."),
     }),
    ("Carga de datos desde Excel", 2, "Escribir mal el nombre del archivo o de la función de lectura.",
     "Ha cargado mi archivo que se llama ventas ejemplo. Ha cargado su hoja y ahora vamos a mostrar sus resultados.", {
         "basico": V("completar", "Completa la instrucción que carga un Excel con pandas: df = pd.____('ventas_ejemplo.xlsx')",
                     "pandas lee archivos de Excel con read_excel y deja los datos en un DataFrame.",
                     ["Es una función de pandas para leer.", "Su nombre combina «leer» en inglés y el tipo de archivo.",
                      "read_...?"], aceptadas=["read_excel", "read_excel()"]),
         "intermedio": V("alternativas",
                         "Cargaste 'ventas_ejemplo.xlsx' y quieres comprobar que llegaron las columnas Cliente, Ciudad e Importe venta. ¿Qué haces?",
                         "Mostrar el DataFrame permite ver las columnas cargadas, igual que en el Excel original.",
                         ["Piensa en cómo verificó el docente que la carga funcionó.",
                          "En clase se mostraron los resultados en el mismo notebook.",
                          "Mostrar las primeras filas del DataFrame."],
                         opciones=["Muestro el DataFrame (por ejemplo, df.head()) y reviso sus columnas",
                                   "Vuelvo a abrir el Excel y cuento las filas a mano",
                                   "Genero un gráfico circular", "Instalo Python en mi laptop"],
                         correcta="Muestro el DataFrame (por ejemplo, df.head()) y reviso sus columnas"),
         "avanzado": V("caso",
                       "Al ejecutar la carga aparece un error porque el archivo subido a Colab se llama distinto al que escribe el código. Diagnostica el problema y explica cómo lo corriges.",
                       "El código solo funciona si el nombre del archivo (el parámetro) coincide con el archivo real.",
                       ["Compara lo que escribe el código con lo que subiste.", "El error está en un parámetro, no en Python.",
                        "Cambia el nombre en la instrucción y vuelve a ejecutar."],
                       puntos=["Identifica que el nombre del archivo no coincide",
                               "Corrige el parámetro con el nombre real del archivo",
                               "Vuelve a ejecutar y verifica mostrando los datos"],
                       correcta="El nombre en el código no coincide con el archivo subido. Cambio el parámetro por el nombre real, vuelvo a ejecutar y muestro el DataFrame para verificar."),
     }),
    ("Resúmenes y agrupaciones", 3, "Agrupar por una columna distinta a la que pide la pregunta.",
     "Voy a generar un resumen que me muestre cuánto se ha vendido por cada ciudad. Insertar, tabla dinámica.", {
         "basico": V("alternativas", "En Excel se hizo una tabla dinámica de ventas por ciudad. ¿Qué resultado buscábamos?",
                     "La tabla dinámica resume el importe total vendido en cada ciudad; en Python se obtiene el mismo resumen.",
                     ["Piensa en la pregunta de negocio del ejemplo.", "Se pusieron las ciudades en filas.",
                      "Era «cuánto se ha vendido por cada ciudad»."],
                     opciones=["El importe total de venta por cada ciudad", "La lista de clientes en orden alfabético",
                               "La fecha de la última venta", "El número de hojas del archivo"],
                     correcta="El importe total de venta por cada ciudad"),
         "intermedio": V("completar", "Completa para obtener el total vendido por ciudad: df.groupby('Ciudad')['Importe venta'].____()",
                         "Agrupar por Ciudad y sumar el importe da el mismo resultado que la tabla dinámica.",
                         ["Quieres el total, no el promedio.", "Es la operación de «sumar» en inglés.", "s _ _"],
                         aceptadas=["sum", "sum()"]),
         "avanzado": V("alternativas",
                       "Dos analistas resumen ventas. A: groupby('Ciudad')['Importe venta'].sum(). B: groupby('Cliente')['Importe venta'].sum(). ¿Cuál responde «cuánto se vendió por ciudad» y por qué?",
                       "La columna de agrupación define la pregunta que respondes: por ciudad, se agrupa por Ciudad.",
                       ["Mira la columna dentro de groupby.", "Agrupar por cliente responde otra pregunta.",
                        "La A agrupa por la columna correcta."],
                       opciones=["A, porque agrupa por Ciudad y suma el importe", "B, porque cada cliente pertenece a una ciudad",
                                 "Ambas dan el mismo resultado", "Ninguna: hay que usar un gráfico circular"],
                       correcta="A, porque agrupa por Ciudad y suma el importe"),
     }),
    ("Gráficos con seaborn", 4, "Confundir qué va en cada eje o dónde se cambia el título.",
     "¿Cómo se llama el eje X? Se llama ciudad. ¿Cómo se llama el eje Y? Importe venta. ¿Qué título tiene?", {
         "basico": V("definir", "Explica con tus palabras qué muestran el eje X, el eje Y y el título en el gráfico de importe de venta por ciudad.",
                     "En el ejemplo, el eje X tiene las ciudades, el eje Y el importe de venta y el título dice qué muestra el gráfico.",
                     ["Recuerda las preguntas que hizo el docente sobre el gráfico.",
                      "Uno de los ejes tiene categorías y el otro valores.",
                      "X: ciudad; Y: importe de venta; título: qué muestra."],
                     puntos=["El eje X muestra las categorías (las ciudades)", "El eje Y muestra el valor (el importe de venta)",
                             "El título describe qué muestra el gráfico"],
                     correcta="El eje X tiene las ciudades, el eje Y el importe de venta y el título explica qué muestra el gráfico."),
         "intermedio": V("alternativas", "Quieres que el gráfico se llame «Reporte por ciudad» en vez de «Importe total de venta por ciudad». ¿Qué haces?",
                         "Basta asociar el elemento que quieres cambiar con la parte del código que lo contiene: no hace falta programar desde cero.",
                         ["No necesitas reescribir nada grande.", "Busca dónde aparece el texto del título en el código.",
                          "Cambias ese texto y vuelves a ejecutar."],
                         opciones=["Cambio el texto del título en la parte del código que lo contiene y vuelvo a ejecutar",
                                   "Reescribo todo el código desde cero", "Cambio el nombre de la columna Ciudad en el Excel",
                                   "Instalo otra librería"],
                         correcta="Cambio el texto del título en la parte del código que lo contiene y vuelvo a ejecutar"),
         "avanzado": V("alternativas",
                       "Para ver qué parte de las tardanzas aporta cada área, un compañero propone un gráfico circular y otro uno de columnas. ¿Qué afirmación es correcta?",
                       "El circular muestra proporciones del total; el de columnas facilita comparar áreas entre sí.",
                       ["Piensa en qué pregunta responde cada gráfico.", "Uno muestra partes de un todo.",
                        "El circular muestra proporción; las columnas comparan."],
                       opciones=["El circular muestra la proporción de cada área en el total; el de columnas facilita comparar áreas",
                                 "Solo el circular puede usar datos de Python", "El de columnas no puede tener título",
                                 "Ambos requieren Power BI"],
                       correcta="El circular muestra la proporción de cada área en el total; el de columnas facilita comparar áreas"),
     }),
]
PREVIO_1 = ("Resúmenes y agrupaciones", "Usar una herramienta que no resume datos.", {
    "basico": V("alternativas", "Antes de empezar: en Excel, ¿qué herramienta usas para resumir muchas filas por categoría (por ejemplo, ventas por ciudad)?",
                "La tabla dinámica resume filas por categoría; en el curso harás lo mismo con Python.",
                ["Es una herramienta de Excel para resumir.", "Se inserta desde el menú Insertar.", "Tabla d…"],
                opciones=["Tabla dinámica", "Corrector ortográfico", "Inmovilizar paneles", "Insertar comentario"],
                correcta="Tabla dinámica")})
CLASE_2 = [
    ("Librerías de Python y pandas", 1, "Creer que pandas es un programa aparte y no una librería.",
     "Las librerías nos permiten resumir lo que deberíamos haber hecho en 10 líneas de Python con una sola. Pandas es una de ellas.", {
         "basico": V("alternativas", "Según la clase, ¿qué es pandas?",
                     "pandas es una librería: resume en una línea lo que tomaría muchas líneas de Python.",
                     ["No es un programa aparte.", "Se importa dentro de Python.", "Es una librería para trabajar con datos."],
                     opciones=["Una librería de Python para trabajar con datos", "Un programa de hojas de cálculo",
                               "Un tipo de gráfico", "Un servicio de Google para guardar archivos"],
                     correcta="Una librería de Python para trabajar con datos"),
         "intermedio": V("alternativas", "¿Por qué conviene usar una librería como pandas en vez de escribir todo el código?",
                         "Las librerías resumen en una línea lo que tomaría varias líneas de Python.",
                         ["Piensa en el esfuerzo de escribir código.", "El docente comparó «10 líneas» con «una sola».",
                          "Ahorra líneas de código."],
                         opciones=["Porque resume en una línea lo que tomaría varias líneas de Python",
                                   "Porque así no se necesita ningún dato", "Porque reemplaza a Excel en todo",
                                   "Porque solo funciona en Power BI"],
                         correcta="Porque resume en una línea lo que tomaría varias líneas de Python"),
         "avanzado": V("caso", "Tu equipo necesita cargar datos, graficarlos y luego entrenar un modelo de machine learning. ¿Qué librerías mencionadas en clase usarías en cada parte y por qué?",
                       "Cada propósito tiene librerías: pandas para datos, seaborn o matplotlib para gráficos y scikit-learn para machine learning.",
                       ["Separa el trabajo en tres partes.", "En clase se nombraron librerías para gráficos y para machine learning.",
                        "pandas, seaborn y scikit-learn."],
                       puntos=["pandas para cargar y manipular los datos", "seaborn, matplotlib o plotly para graficar",
                               "scikit-learn para machine learning"],
                       correcta="pandas para cargar y preparar los datos, seaborn para los gráficos y scikit-learn para el modelo."),
     }),
    ("Automatización de reportes", 2, "Automatizar cuando solo se necesita un gráfico.",
     "¿Y cuándo Python es crucial? Cuando este volumen de gráficas es grande, por ejemplo un informe de más de 500 páginas.", {
         "basico": V("alternativas", "¿Cuándo se vuelve crucial automatizar gráficos con Python?",
                     "La automatización vale la pena cuando hay muchas gráficas, como un informe de cientos de páginas.",
                     ["Piensa en el volumen de trabajo.", "El ejemplo fue un informe muy grande.", "Cuando hay muchas gráficas."],
                     opciones=["Cuando el volumen de gráficas es grande", "Cuando solo se necesita un gráfico",
                               "Cuando no hay datos", "Cuando el dashboard ya está en Power BI"],
                     correcta="Cuando el volumen de gráficas es grande"),
         "intermedio": V("completar", "Python generó las gráficas y las guardó en un archivo de ____ para que solo agregues una descripción debajo de cada una.",
                         "En la clase, el archivo generado se abrió en PowerPoint con las gráficas listas.",
                         ["Es un programa de presentaciones.", "Se usa para diapositivas.", "Power…"],
                         aceptadas=["PowerPoint", "PPT", "pptx", "Power Point"]),
         "avanzado": V("caso", "Cada mes preparas 40 gráficos por región para un informe. Compara hacerlo a mano en Excel y con un bloque de código en Python, y justifica cuál eliges.",
                       "Con muchos gráficos repetitivos, un bloque de código con parámetros evita trabajo manual y errores.",
                       ["Cuenta cuántas veces repetirías el trabajo manual.", "Piensa en qué cambia de un mes a otro.",
                        "El código se reutiliza cambiando parámetros."],
                       puntos=["Reconoce que a mano es repetitivo y lento con muchos gráficos",
                               "Explica que el código se reutiliza cambiando parámetros",
                               "Elige Python y lo justifica por el volumen"],
                       correcta="A mano repetiría 40 gráficos cada mes. Con Python reutilizo el bloque cambiando parámetros, así que elijo Python por el volumen."),
         "maestria": V("caso", "Diseña un flujo automatizado para tu reporte mensual: desde cargar el Excel hasta entregar el PowerPoint. Describe los pasos y qué parámetros cambiarías cada mes.",
                       "Se evalúa con la rúbrica del tema: carga, gráficos reutilizables, exportación automática y mantenimiento.",
                       ["Empieza por el archivo de origen.", "Piensa en qué partes del código cambian cada mes.",
                        "Carga → gráficos con parámetros → exportación al PowerPoint."],
                       puntos=[c["criterio"] + ": " + c["descripcion"] for c in RUBRICA_AUTOMATIZACION],
                       correcta="Cargo el Excel con pandas, genero los gráficos con un bloque parametrizado por mes y región y los exporto automáticamente al PowerPoint; cada mes solo cambio el archivo y los títulos."),
     }),
    ("IA como apoyo para programar", 3, "Copiar el código de la IA sin adaptar sus parámetros.",
     "Hoy en día tenemos el apoyo de la inteligencia artificial para poderle pedir bloques de código.", {
         "basico": V("alternativas", "En la clase, ¿para qué se usó la inteligencia artificial?",
                     "Se le pidió un bloque de código para subir un Excel a Colab, con alternativas y explicación.",
                     ["No reemplaza al analista.", "Se le pidió algo concreto.", "Bloques de código."],
                     opciones=["Para pedir bloques de código, como subir un Excel a Colab",
                               "Para reemplazar al analista en todo el análisis", "Para crear la base de datos de ventas",
                               "Para pagar el curso"],
                     correcta="Para pedir bloques de código, como subir un Excel a Colab"),
         "intermedio": V("alternativas", "La IA te dio código para subir un Excel a Colab con dos alternativas. ¿Qué haces antes de usarlo?",
                         "El código de la IA se entiende, se elige y se prueba con tus propios datos.",
                         ["No lo uses a ciegas.", "La IA explicó para qué sirve cada alternativa.", "Lee, elige y prueba."],
                         opciones=["Leo la explicación, elijo una alternativa y la pruebo con mi archivo",
                                   "Pego ambas alternativas sin leerlas", "Lo descarto porque la IA siempre se equivoca",
                                   "Lo paso directamente a Power BI"],
                         correcta="Leo la explicación, elijo una alternativa y la pruebo con mi archivo"),
         "avanzado": V("caso", "La IA generó código que carga 'ventas.xlsx', pero tu archivo se llama 'ventas_ejemplo.xlsx' y da error. Diagnostica el problema y explica cómo lo corriges.",
                       "Los bloques de código se adaptan cambiando sus parámetros, como el nombre del archivo.",
                       ["Compara el nombre del código con el de tu archivo.", "Es un parámetro.", "Cambia el nombre y vuelve a ejecutar."],
                       puntos=["Identifica que el nombre del archivo no coincide", "Cambia el parámetro por el nombre correcto",
                               "Vuelve a ejecutar y verifica los datos"],
                       correcta="El nombre del archivo en el código no coincide; cambio el parámetro a 'ventas_ejemplo.xlsx', ejecuto y reviso los datos."),
     }),
    ("Limpieza y transformación de datos", 4, "Analizar datos incompletos sin prepararlos.",
     "La data no siempre está completa, no siempre está correcta. Hay que completar datos que faltan, crear nuevos datos, juntar tablas.", {
         "basico": V("definir", "Explica con tus palabras por qué la data necesita limpieza antes de construir un dashboard.",
                     "La data no siempre está completa ni correcta; hay que completarla, corregirla o crear datos nuevos.",
                     ["Piensa en cómo llega la data normalmente.", "¿Siempre está completa?", "Faltan datos o hay errores."],
                     puntos=["La data no siempre está completa o correcta", "Hay que completar, corregir o crear datos antes de usarla"],
                     correcta="Porque la data puede venir incompleta o con errores, y hay que completarla o corregirla antes de usarla."),
         "intermedio": V("alternativas", "Tienes una tabla de trabajadores y otra con sus áreas. ¿Qué tarea de procesamiento necesitas para tener todo junto?",
                         "Juntar tablas es parte del procesamiento que se mencionó en clase.",
                         ["Tienes dos tablas.", "Necesitas combinarlas.", "Juntar (unir) tablas."],
                         opciones=["Juntar (unir) las tablas", "Cambiar el título del gráfico", "Generar un gráfico circular",
                                   "Crear una cuenta de Gmail"], correcta="Juntar (unir) las tablas"),
     }),
]


RUBRICA_SPARK = [
    {"criterio": "Lectura distribuida", "descripcion": "Carga los datos en un DataFrame de Spark desde el almacenamiento."},
    {"criterio": "Transformaciones", "descripcion": "Encadena filtros, agrupaciones o uniones sin traer los datos al driver."},
    {"criterio": "Acciones y resultados", "descripcion": "Distingue cuándo una acción dispara el cálculo (evaluación perezosa)."},
]
MALLA_BD = (
    ("Fundamentos de Big Data", "Las 5 V del Big Data",
     "Explicar volumen, velocidad, variedad, veracidad y valor con ejemplos de negocio.", "avanzado", True),
    ("Fundamentos de Big Data", "Data lake y data warehouse",
     "Distinguir un data lake de un data warehouse y decidir cuándo usar cada uno.", "avanzado", True),
    ("Fundamentos de Big Data", "Procesamiento batch y streaming",
     "Diferenciar el procesamiento por lotes del procesamiento en tiempo real según la latencia necesaria.", "avanzado", False),
    ("Ecosistema de procesamiento", "Hadoop y HDFS",
     "Describir cómo HDFS reparte archivos en bloques replicados entre varios nodos.", "intermedio", False),
    ("Ecosistema de procesamiento", "Apache Spark y DataFrames",
     "Procesar datos distribuidos con DataFrames de Spark, distinguiendo transformaciones y acciones.", "maestria", True),
    ("Ecosistema de procesamiento", "Spark SQL",
     "Consultar grandes volúmenes de datos con SQL distribuido.", "avanzado", False),
    ("Datos en la nube y gobierno", "Servicios de Big Data en la nube",
     "Identificar servicios gestionados de almacenamiento y procesamiento y su modelo de costos.", "intermedio", False),
    ("Datos en la nube y gobierno", "Calidad y gobierno de datos",
     "Aplicar reglas de calidad, linaje y privacidad sobre los datos del negocio.", "avanzado", True),
)
TRANSCRIPT_BD = """Buenas noches a todos. Hoy empezamos la especialización con los fundamentos de Big Data.
Cuando hablamos de Big Data no hablamos solo de muchos datos: usamos las cinco V. Volumen, porque hablamos de
terabytes o petabytes. Velocidad, porque los datos llegan todo el tiempo; piensen en las ubicaciones GPS de una
app de delivery, miles por segundo. Variedad, porque conviven tablas, textos, imágenes, videos y archivos JSON.
Veracidad, porque si los datos tienen duplicados o campos vacíos las decisiones salen mal. Y valor, que es lo que
realmente buscamos: que los datos ayuden a decidir.

Luego vimos dónde guardar los datos. Un data lake guarda los datos en bruto, en cualquier formato, sin definir un
esquema antes; es ideal para explorar, por ejemplo logs, imágenes o JSON que todavía no sabemos cómo usar. Un data
warehouse guarda datos limpios y estructurados, listos para consultas SQL y reportes, como los reportes mensuales
de finanzas.

Sobre el procesamiento: en batch procesamos bloques de datos acumulados cada cierto tiempo, como el reporte de
ventas del día anterior que corre de noche. En streaming procesamos cada evento apenas llega, como la detección de
fraude mientras ocurre la compra o una alerta inmediata de quiebre de stock.

Finalmente, Hadoop. Su sistema de archivos, HDFS, divide cada archivo en bloques y los reparte entre varios nodos.
Además guarda copias de cada bloque, por defecto tres, para que si un nodo falla no perdamos información. La
próxima clase trabajaremos con Apache Spark y sus DataFrames."""
CLASE_1_BD = [
    ("Las 5 V del Big Data", 1, "Reducir Big Data solo al volumen de los datos.",
     "Usamos las cinco V: volumen, velocidad, variedad, veracidad y valor.", {
         "basico": V("alternativas", "¿Qué «V» del Big Data se refiere a la rapidez con la que se generan y procesan los datos?",
                     "La velocidad describe el ritmo con el que llegan los datos, como las ubicaciones GPS por segundo de una app de delivery.",
                     ["Piensa en el ejemplo de la app de delivery.", "No es la cantidad, es el ritmo.", "Empieza con «Vel…»."],
                     opciones=["Velocidad", "Volumen", "Variedad", "Veracidad"], correcta="Velocidad"),
         "intermedio": V("alternativas",
                         "Una app de delivery registra miles de ubicaciones GPS por segundo, además de fotos y reseñas de texto. ¿Qué dos V describen mejor este caso?",
                         "Miles de eventos por segundo es velocidad; fotos, texto y coordenadas juntos es variedad.",
                         ["Hay dos características distintas en el enunciado.", "Una habla del ritmo y otra de los formatos.",
                          "Ritmo de llegada y diversidad de formatos."],
                         opciones=["Velocidad y variedad", "Volumen y veracidad", "Valor y volumen", "Veracidad y variedad"],
                         correcta="Velocidad y variedad"),
         "avanzado": V("caso",
                       "Un banco tiene muchos datos, pero sus reportes no ayudan a decidir porque hay registros duplicados y campos vacíos. Analiza qué V está fallando y propone cómo mejorarla.",
                       "La veracidad (calidad) de los datos condiciona el valor: sin datos confiables no hay buenas decisiones.",
                       ["El problema no es la cantidad.", "Piensa en la calidad de los registros.", "Es la veracidad: limpiar y validar."],
                       puntos=["Identifica la veracidad (calidad de los datos) como el problema",
                               "Propone eliminar duplicados y completar o validar campos",
                               "Relaciona la mejora con obtener valor para decidir"],
                       correcta="Falla la veracidad. Eliminaría duplicados y validaría los campos obligatorios para que los reportes sean confiables y generen valor."),
     }),
    ("Data lake y data warehouse", 2, "Cargar datos sin estructura a un data warehouse.",
     "Un data lake guarda los datos en bruto, en cualquier formato; un data warehouse guarda datos limpios y estructurados.", {
         "basico": V("completar", "Un repositorio que guarda datos en bruto, en cualquier formato y sin esquema previo, se llama data ____.",
                     "El data lake admite datos en bruto de cualquier formato; el esquema se define al leerlos.",
                     ["Es lo contrario del almacén estructurado.", "En inglés es un cuerpo de agua.", "Data l…"],
                     aceptadas=["lake", "data lake"]),
         "intermedio": V("alternativas",
                         "El área de finanzas necesita reportes mensuales con datos limpios y estructurados que se consultan con SQL. ¿Dónde conviene guardarlos?",
                         "El data warehouse está pensado para datos estructurados y consultas SQL de reporte.",
                         ["Piensa en datos ya limpios y con estructura.", "El ejemplo de finanzas de la clase.", "Data w…"],
                         opciones=["En un data warehouse", "En un data lake sin procesar", "En hojas de cálculo sueltas",
                                   "En los logs del servidor"], correcta="En un data warehouse"),
         "avanzado": V("alternativas",
                       "Un equipo de ciencia de datos quiere explorar logs, imágenes y JSON sin haber definido todavía cómo los usará. ¿Qué decisión es más adecuada y por qué?",
                       "Para explorar datos heterogéneos sin esquema conviene el data lake; el warehouse exige definir la estructura antes.",
                       ["Fíjate en que aún no hay esquema.", "¿Qué repositorio acepta cualquier formato?", "Primero el data lake."],
                       opciones=["Guardarlos primero en un data lake, porque admite datos en bruto de cualquier formato",
                                 "Cargarlos directo al data warehouse, porque exige un esquema definido",
                                 "Descartarlos hasta tener un esquema", "Convertirlos todos a Excel"],
                       correcta="Guardarlos primero en un data lake, porque admite datos en bruto de cualquier formato"),
     }),
    ("Procesamiento batch y streaming", 3, "Usar un proceso nocturno cuando se necesita reaccionar al instante.",
     "En batch procesamos bloques acumulados; en streaming procesamos cada evento apenas llega.", {
         "basico": V("alternativas", "¿Qué caracteriza al procesamiento batch?",
                     "Batch procesa bloques de datos acumulados cada cierto tiempo, como el reporte nocturno de ventas.",
                     ["Piensa en el reporte del día anterior.", "No es en tiempo real.", "Bloques cada cierto tiempo."],
                     opciones=["Procesa bloques de datos acumulados cada cierto tiempo", "Procesa cada evento apenas llega",
                               "Solo funciona con imágenes", "No necesita almacenar datos"],
                     correcta="Procesa bloques de datos acumulados cada cierto tiempo"),
         "intermedio": V("alternativas", "Detectar un fraude con tarjeta mientras ocurre la compra requiere…",
                         "Reaccionar durante la compra exige procesar cada evento al llegar: streaming.",
                         ["¿Cuánto puede esperar la respuesta?", "No sirve esperar a la noche.", "Tiempo real."],
                         opciones=["Procesamiento en streaming (tiempo real)", "Un proceso batch nocturno", "Un reporte mensual",
                                   "Un data warehouse sin actualizar"], correcta="Procesamiento en streaming (tiempo real)"),
         "avanzado": V("caso",
                       "Una cadena de tiendas quiere el reporte de ventas del día anterior y, además, alertas inmediatas de quiebre de stock. Compara batch y streaming y justifica qué usarías en cada caso.",
                       "La latencia necesaria decide: el reporte tolera horas (batch); la alerta necesita segundos (streaming).",
                       ["Hay dos necesidades distintas.", "Compara cuánto puede esperar cada una.", "Batch para el reporte, streaming para la alerta."],
                       puntos=["Usa batch para el reporte diario de ventas", "Usa streaming para las alertas inmediatas de stock",
                               "Justifica según la latencia que necesita cada caso"],
                       correcta="Batch para el reporte del día anterior porque puede esperar a la noche; streaming para las alertas porque deben llegar al instante."),
     }),
    ("Hadoop y HDFS", 4, "Creer que HDFS guarda cada archivo completo en un solo servidor.",
     "HDFS divide cada archivo en bloques, los reparte entre nodos y guarda copias, por defecto tres.", {
         "basico": V("alternativas", "¿Por qué HDFS divide los archivos en bloques y guarda réplicas?",
                     "Repartir bloques permite almacenar archivos enormes en varios nodos, y las réplicas evitan perder datos si uno falla.",
                     ["Piensa en qué pasa si un nodo falla.", "Son varios servidores trabajando juntos.", "Distribuir y tolerar fallas."],
                     opciones=["Para distribuir el almacenamiento y tolerar fallas de nodos", "Para comprimir imágenes",
                               "Para que cada archivo ocupe menos de 1 MB", "Para evitar usar varios servidores"],
                     correcta="Para distribuir el almacenamiento y tolerar fallas de nodos"),
         "intermedio": V("completar", "Por defecto, HDFS guarda cada bloque ____ veces (factor de replicación).",
                         "El factor de replicación por defecto es tres: si un nodo falla, quedan otras copias.",
                         ["Es un número pequeño.", "Más de dos.", "Tr…"], aceptadas=["3", "tres"]),
     }),
]
PREVIO_1_BD = ("Las 5 V del Big Data", "Confundir datos estructurados y no estructurados.", {
    "basico": V("alternativas", "Antes de empezar: ¿cuál de estos es un ejemplo de dato no estructurado?",
                "Un video no tiene filas ni columnas fijas: es un dato no estructurado, parte de la variedad del Big Data.",
                ["Piensa en algo sin filas ni columnas.", "No es una tabla.", "Un archivo multimedia."],
                opciones=["Un video de una cámara de seguridad", "Una tabla de clientes con columnas fijas",
                          "Un registro de ventas en SQL", "Una hoja con fecha y monto"],
                correcta="Un video de una cámara de seguridad")})


def _usuario(db, dni, nombre, apellido, rol) -> Usuario:
    usuario = db.scalar(select(Usuario).where(Usuario.dni == dni))
    if usuario is None:
        usuario = Usuario(dni=dni, nombre=nombre, apellido=apellido, rol=rol,
                          password_hash=hash_password(settings.DEMO_PASSWORD))
        db.add(usuario)
        db.flush()
    return usuario


def curso_demo(db) -> Curso | None:
    return db.scalar(select(Curso).where(Curso.nombre == CURSO))


def curso_big_data(db) -> Curso | None:
    return db.scalar(select(Curso).where(Curso.nombre == CURSO_BD))


def _curso(db, nombre: str, malla, rubrica: list, lenguajes: list, dias: int, docente: Usuario,
           alumnos: list[Usuario]) -> Curso:
    curso = db.scalar(select(Curso).where(Curso.nombre == nombre))
    if curso is None:
        curso = Curso(nombre=nombre, fecha_inicio=date.today() - timedelta(days=dias), lenguajes=lenguajes,
                      propuesta_estado="lista")
        db.add(curso)
        db.flush()
    for persona in [docente, *alumnos]:
        if db.get(Inscripcion, (persona.id, curso.id)) is None:
            db.add(Inscripcion(usuario_id=persona.id, curso_id=curso.id,
                               rol_en_curso="docente" if persona.rol == "docente" else "alumno"))
    if not db.scalar(select(Tema.id).where(Tema.curso_id == curso.id).limit(1)):
        for orden, (modulo, tema, objetivo, maximo, fundamental) in enumerate(malla, start=1):
            db.add(Tema(curso_id=curso.id, modulo=modulo, nombre=tema, subtema="", orden=orden, objetivo=objetivo,
                        nivel_maximo=maximo, es_fundamental=fundamental, propuesto_por_ia=True,
                        rubrica=rubrica if maximo == "maestria" else [], lenguaje=lenguajes[0] if lenguajes else None))
    db.flush()
    return curso


def cuentas_y_malla(db) -> Curso:
    """Both demo courses with their accounts and malla. Returns the Python course."""
    _usuario(db, *ADMIN)
    alumnos = {dni: _usuario(db, dni, nombre, apellido, "alumno") for dni, nombre, apellido in ALUMNOS}
    python = _curso(db, CURSO, MALLA, RUBRICA_AUTOMATIZACION, ["Python"], 14, _usuario(db, *DOCENTE),
                    list(alumnos.values()))
    _curso(db, CURSO_BD, MALLA_BD, RUBRICA_SPARK, ["Python", "SQL"], 30, _usuario(db, *DOCENTE_BD),
           [alumnos[dni] for dni in ALUMNOS_BD])
    privacy.invalidar_cache()
    return python


def _transcript() -> str:
    archivos = sorted(settings.SAMPLE_DIR.glob("*sin_marcas*.md")) or sorted(settings.SAMPLE_DIR.glob("*.md"))
    archivos = [a for a in archivos if a.name.lower() != "readme.md"]
    if archivos:
        return archivos[0].read_text(encoding="utf-8")
    return "Clase de demostración sobre Python para analistas: extraer, limpiar, analizar y visualizar datos."


def _crear_clase(db, curso, docente, numero, titulo, fecha, retos, previo=None, estado="publicada", *,
                 texto: str, fuente: str, tarea: str | None = None) -> Clase:
    from services.classes import crear_reto
    temas = {t.nombre: t for t in db.scalars(select(Tema).where(Tema.curso_id == curso.id))}
    momento = ahora()
    clase = Clase(curso_id=curso.id, numero=numero, fecha=fecha, titulo=titulo, fuente_tipo="texto",
                  fuente_nombre=fuente, transcript=texto,
                  transcript_anon=anonimizar(texto, privacy.conocidos(forzar=True)), estado=estado,
                  aviso_docente_en=momento - timedelta(minutes=8), creado_por=docente.id,
                  vence_validacion_en=momento + timedelta(minutes=52) if estado == "por_validar" else None,
                  publicada_en=momento - timedelta(days=(date.today() - fecha).days) if estado == "publicada" else None,
                  tarea=tarea)
    db.add(clase)
    db.flush()
    for nombre, posicion, error_comun, cita, versiones in retos:
        tema = temas[nombre]
        if db.get(ClaseTema, (clase.id, tema.id)) is None:
            db.add(ClaseTema(clase_id=clase.id, tema_id=tema.id, evidencia=cita, confianza=0.9 - posicion / 20))
        crear_reto(db, curso_id=curso.id, clase_id=clase.id, posicion=posicion,
                   estado="aprobado" if estado == "publicada" else "propuesto",
                   generado=RetoGenerado(posicion, tema.id, error_comun, "transcript", cita, versiones))
    if estado == "publicada":
        from services.messages import encolar_clase_nueva
        encolar_clase_nueva(db, clase)
    if previo:
        nombre, error_comun, versiones = previo
        crear_reto(db, curso_id=curso.id, clase_id=clase.id, uso="previo", estado="aprobado" if estado == "publicada" else "propuesto",
                   generado=RetoGenerado(None, temas[nombre].id, error_comun, "malla", "Objetivo del tema en la malla", versiones))
    return clase


def _respuesta(version: RetoVersion, acierta: bool) -> str:
    if version.tipo == "alternativas":
        return version.respuesta_correcta if acierta else next(o for o in version.opciones if o != version.respuesta_correcta)
    if version.tipo == "completar":
        return version.respuesta_correcta if acierta else "no recuerdo"
    return ("Respuesta de práctica que cubre las ideas: " + "; ".join(version.puntos_clave)) if acierta else \
        "Respuesta de práctica incompleta sobre el tema, sin las ideas principales."


def _practicar(db, alumno, clase, perfil, params) -> None:
    """perfil: list of (acierta, pistas) per challenge. Open answers are graded by rule here (no AI in the demo)."""
    from services import attempts, quiz as quiz_service
    alumno.consentimiento_en = alumno.consentimiento_en or ahora()
    quiz = quiz_service.generar(db, alumno, clase, params)
    for acierta, pistas in perfil:
        item = quiz_service.item_actual(db, quiz)
        if item is None:
            break
        version, reto, _ = quiz_service.preparar(db, alumno, quiz, item)
        item.presentado_en = ahora() - timedelta(seconds=40 + 25 * item.orden)  # realistic hidden timing
        for _ in range(pistas):
            quiz_service.pedir_pista(db, quiz, item.id)
        intento, abierta = quiz_service.responder(db, alumno, quiz, item.id, _respuesta(version, acierta),
                                                  f"demo-{alumno.id}-{item.id}", params)
        if abierta:
            resultado = "correcto" if acierta else "incorrecto"
            attempts.finalizar(db, intento, resultado, {
                "veredicto": resultado, "bien": "Explicaste el tema con tus palabras.",
                "falto": "Revisa los puntos clave del reto en la clase.", "ejemplo_o_pista": "" if acierta else version.pistas[0],
                "fuente_usada": reto.fuente_ref}, params)
        quiz_service.seguir(db, quiz, params)
    # A student who already practiced has been in the course: the new-class notice was already seen.
    db.execute(update(Mensaje).where(Mensaje.alumno_id == alumno.id, Mensaje.curso_id == clase.curso_id,
                                     Mensaje.estado == "pendiente").values(estado="mostrado", mostrado_en=ahora()))


def _atrasar(db, alumno_ids: list[int], curso_id: int, dias: int) -> None:
    """Move simulated practice back in time (activity dates and the review agenda)."""
    hace = timedelta(days=dias)
    db.execute(update(Intento).where(Intento.alumno_id.in_(alumno_ids), Intento.curso_id == curso_id).values(
        creado_en=Intento.creado_en - hace, completado_en=Intento.completado_en - hace))
    db.execute(update(Quiz).where(Quiz.alumno_id.in_(alumno_ids), Quiz.curso_id == curso_id).values(
        creado_en=Quiz.creado_en - hace, completado_en=Quiz.completado_en - hace))
    temas = select(Tema.id).where(Tema.curso_id == curso_id)
    db.execute(update(AgendaRepaso).where(AgendaRepaso.alumno_id.in_(alumno_ids), AgendaRepaso.tema_id.in_(temas))
               .values(proxima_fecha=AgendaRepaso.proxima_fecha - hace))


def _actividad_python(db, curso, alumnos, params) -> bool:
    if db.scalar(select(Clase.id).where(Clase.curso_id == curso.id, Clase.numero.in_((1, 2)))):
        return False
    docente = db.scalar(select(Usuario).where(Usuario.dni == DOCENTE[0]))
    hoy = date.today()
    clase_1 = _crear_clase(db, curso, docente, 1, "Python para analistas: automatiza tus reportes",
                           hoy - timedelta(days=10), CLASE_1, PREVIO_1, texto=_transcript(),
                           fuente="Transcript de la master class (demo)",
                           tarea="Replica en Colab el resumen de ventas por ciudad con tu propio archivo.")
    perfiles = {
        "70000002": [(True, 0)] * 4,                                   # Diego: quiz perfecto
        "70000003": [(True, 0), (True, 1), (True, 0), (False, 0)],     # Valeria
        "70000004": [(False, 0), (False, 1), (True, 2), (False, 0)],   # Andrés
        "70000005": [(True, 0), (False, 0), (True, 1), (True, 0)],     # Camila (luego inactiva)
    }
    for dni, perfil in perfiles.items():
        _practicar(db, alumnos[dni], clase_1, perfil, params)
    db.flush()
    # Camila practiced 9 days ago and has not come back: she appears in the risk panel.
    _atrasar(db, [alumnos["70000005"].id], curso.id, 9)
    # Due reviews, so the next class quiz includes a REPASO challenge.
    temas = select(Tema.id).where(Tema.curso_id == curso.id)
    db.execute(update(AgendaRepaso).where(AgendaRepaso.alumno_id.in_([a.id for a in alumnos.values()]),
                                          AgendaRepaso.tema_id.in_(temas)).values(proxima_fecha=ahora() - timedelta(hours=2)))
    _crear_clase(db, curso, docente, 2, "Librerías, automatización e IA como apoyo", hoy - timedelta(days=1),
                 CLASE_2, estado="por_validar", texto=_transcript(), fuente="Transcript de la master class (demo)")
    return True


def _actividad_big_data(db, curso, alumnos, params) -> bool:
    if db.scalar(select(Clase.id).where(Clase.curso_id == curso.id)):
        return False
    docente = db.scalar(select(Usuario).where(Usuario.dni == DOCENTE_BD[0]))
    clase_1 = _crear_clase(db, curso, docente, 1, "Fundamentos de Big Data y arquitectura de datos",
                           date.today() - timedelta(days=6), CLASE_1_BD, PREVIO_1_BD, texto=TRANSCRIPT_BD,
                           fuente="Transcript de la clase 1 (demo)")
    perfiles = {
        # Lucía already took this course's first quiz: she is a returning student with two courses.
        "70000001": [(True, 0), (False, 0), (True, 1), (True, 0)],
        "70000002": [(True, 0), (True, 0), (False, 0), (True, 0)],
        "70000003": [(True, 0), (True, 0), (True, 0), (True, 0)],
    }
    for dni, perfil in perfiles.items():
        _practicar(db, alumnos[dni], clase_1, perfil, params)
    db.flush()
    # They practiced three days ago, so their first reviews are already due.
    _atrasar(db, [alumnos[dni].id for dni in perfiles], curso.id, 3)
    return True


def actividad(db) -> bool:
    """Classes and simulated practice for both courses. Returns False if everything was already loaded."""
    from services.params import cargar
    python = cuentas_y_malla(db)
    params = cargar(db)
    alumnos = {u.dni: u for u in db.scalars(select(Usuario).where(Usuario.dni.in_([a[0] for a in ALUMNOS])))}
    cargado_python = _actividad_python(db, python, alumnos, params)
    cargado_bd = _actividad_big_data(db, curso_big_data(db), alumnos, params)
    return cargado_python or cargado_bd


if __name__ == "__main__":
    from db.session import SessionLocal
    with SessionLocal.begin() as sesion:
        print("Datos de demostración cargados." if actividad(sesion) else "La demostración ya estaba cargada.")
