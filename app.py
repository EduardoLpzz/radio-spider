print("--- [SISTEMA FINAL] RADIO SUEÑO PRO (v15.0: CLOUD FIXED) ---")
from flask import Flask, render_template, jsonify, request
from gtts import gTTS
import os
import random
import socket
import requests
from datetime import datetime
import time
import yt_dlp
import google.generativeai as genai
from mutagen.mp3 import MP3
import re 
import threading 
import imageio_ffmpeg # <--- NUEVO: Para que funcione en la nube

# Configuración explícita de carpetas para evitar errores en Render
app = Flask(__name__, template_folder='templates', static_folder='static')

# ==========================================
# 🔑 TU API KEY
API_KEY_GOOGLE = "AIzaSyBrUwZ3CVp6gJ1r9Klp3Z_rVLiKitwlFF4"
# ==========================================

try:
    genai.configure(api_key=API_KEY_GOOGLE)
    model = genai.GenerativeModel('gemini-1.5-flash')
    print("✅ CEREBRO IA: CONECTADO")
except: print("⚠️ ERROR IA: REVISAR API KEY")

# --- CONFIGURACIÓN ---
MAXIMO_CANCIONES = 40
CLAVE_ADMIN = "5256"
LAT = "15.50" 
LON = "-88.02"

# --- VARIABLES DE ESTADO ---
estado_radio = {
    "archivo_actual": None,
    "titulo_actual": "Iniciando...",
    "artista_actual": "Radio Sueño",
    "imagen_actual": None,
    "hora_inicio_timestamp": 0, 
    "duracion_total": 0,
    "ultimo_slot_anunciado": None 
}

cola_humanos = [] 
cola_ia = []      

historial_visual = [] 
canciones_ya_sonadas = set() 

cancion_pendiente_post_intro = None 
en_proceso_de_cambio = False 
usuarios_conectados = {} 
mensaje_overlay = {"archivo": None, "id": 0, "expiracion": 0}

ultimo_anuncio_hora = time.time() - 3600 

# --- FUNCIONES ---

def limpiar_titulo_pro(nombre):
    nombre = nombre.replace(".mp3", "")
    patron = r'[\(\[\{].*?(video|lyric|liro|official|oficial|audio|hd|4k|visualizer).*?[\)\]\}]'
    nombre = re.sub(patron, '', nombre, flags=re.IGNORECASE)
    nombre = nombre.replace("- Topic", "").replace("Official", "")
    return " ".join(nombre.split())

def obtener_hora_texto(): return datetime.now().strftime("%I:%M %p")

def obtener_clima():
    try:
        url = f"https://api.open-meteo.com/v1/forecast?latitude={LAT}&longitude={LON}&current=temperature_2m&timezone=auto"
        r = requests.get(url, timeout=1).json()
        temp = r['current']['temperature_2m']
        return f"{int(temp)}°C"
    except: return "un clima agradable"

def obtener_duracion(archivo_path):
    try:
        audio = MP3(archivo_path)
        return audio.info.length 
    except: return 10 

def generar_voz(texto):
    print(f"🗣️ HABLANDO: {texto}")
    archivo = "static/voz_temp.mp3"
    texto_seguro = texto + " . . ."
    try:
        if os.path.exists(archivo): os.remove(archivo)
    except: pass
    try:
        tts = gTTS(text=texto_seguro, lang='es', tld='com.mx')
        tts.save(archivo)
        return f"voz_temp.mp3?v={int(time.time())}", obtener_duracion("static/voz_temp.mp3")
    except: return None, 5

def limpiar_archivos_antiguos():
    carpeta = 'static'
    archivos = [f for f in os.listdir(carpeta) if f.endswith('.mp3') and "voz_temp" not in f]
    if len(archivos) > MAXIMO_CANCIONES:
        archivos.sort(key=lambda x: os.path.getctime(os.path.join(carpeta, x)))
        for i in range(len(archivos) - MAXIMO_CANCIONES):
            archivo_a_borrar = archivos[i]
            if archivo_a_borrar == estado_radio["archivo_actual"]: continue 
            try: os.remove(os.path.join(carpeta, archivo_a_borrar))
            except: pass

def generar_presentacion_ia(cancion, tipo="NORMAL"):
    titulo_limpio = limpiar_titulo_pro(cancion)
    hora = obtener_hora_texto()
    clima = obtener_clima()
    try:
        prompt = ""
        if tipo == "HORA":
            prompt = f"Eres Locutor. Son las {hora}, {clima}. Presenta: '{titulo_limpio}'. Di la hora exacta. Max 20 palabras."
        elif tipo == "CURIOSO":
            prompt = f"Eres DJ. Di un dato curioso sobre el ARTISTA o GÉNERO de '{titulo_limpio}'. NO digas el nombre de la cancion. Max 15 palabras."
        response = model.generate_content(prompt)
        return response.text.strip()
    except: 
        if tipo == "HORA": return f"Son las {hora}."
        return "" 

def buscar_portada_itunes(termino):
    try:
        termino_clean = limpiar_titulo_pro(termino)
        url = f"https://itunes.apple.com/search?term={termino_clean}&media=music&limit=1"
        r = requests.get(url, timeout=1).json()
        if r['resultCount'] > 0: return r['results'][0]['artworkUrl100'].replace('100x100', '600x600')
    except: pass
    return None

# --- DESCARGA ARREGLADA PARA LA NUBE ---
def descargar_cancion(input_usuario, es_automatico=False, ignorar_repetidas=False):
    try:
        limpiar_archivos_antiguos()
        nombres_descargados = [] 
        
        if not input_usuario.startswith("http"):
            if es_automatico:
                busqueda_forzada = f"{input_usuario} audio oficial"
                query = f"ytsearch3:{busqueda_forzada}"
            else:
                busqueda_forzada = f"{input_usuario} cancion audio oficial"
                query = f"ytsearch1:{busqueda_forzada}"
        else:
            query = input_usuario

        print(f"🔎 BUSCANDO ({'AUTO' if es_automatico else 'MANUAL'}): {query}")

        opciones = {
            'format': 'bestaudio/best', 
            'outtmpl': 'static/%(title)s.%(ext)s', 
            'postprocessors': [{'key': 'FFmpegExtractAudio','preferredcodec': 'mp3','preferredquality': '192'}], 
            # FIX PARA LA NUBE: Usamos el ffmpeg de la librería imageio
            'ffmpeg_location': imageio_ffmpeg.get_ffmpeg_exe(), 
            'quiet': True, 
            'ignoreerrors': True,
            'match_filter': 'duration < 480 & duration > 60' 
        }
        
        with yt_dlp.YoutubeDL(opciones) as ydl:
            info = ydl.extract_info(query, download=True)
            
            if 'entries' in info:
                for entrada in info['entries']:
                    if not entrada: continue
                    titulo_check = entrada.get('title', 'Desconocido')
                    
                    if not ignorar_repetidas and titulo_check in canciones_ya_sonadas:
                        print(f"🚫 YA SONÓ: {titulo_check}")
                        continue
                    
                    filename = os.path.basename(ydl.prepare_filename(entrada))
                    final_name = f"{os.path.splitext(filename)[0]}.mp3"
                    nombres_descargados.append(final_name)
            else:
                titulo_check = info.get('title', 'Desconocido')
                if ignorar_repetidas or titulo_check not in canciones_ya_sonadas:
                    filename = os.path.basename(ydl.prepare_filename(info))
                    final_name = f"{os.path.splitext(filename)[0]}.mp3"
                    nombres_descargados.append(final_name)

            if len(nombres_descargados) > 0:
                return True, info.get('title', 'Varios'), nombres_descargados
            else:
                return False, "Repetida o Muy Larga", []

    except Exception as e: 
        print(f"❌ ERROR: {e}")
        return False, str(e), []

def actualizar_historial_visual(cancion):
    titulo = limpiar_titulo_pro(cancion)
    if historial_visual and historial_visual[0] == titulo: return
    historial_visual.insert(0, titulo)
    if len(historial_visual) > 10: historial_visual.pop()
    canciones_ya_sonadas.add(titulo) 
    canciones_ya_sonadas.add(cancion.replace(".mp3", "")) 

def intentar_llenar_cola_inteligente(cancion_anterior):
    artista_detectado = None
    if " - " in cancion_anterior: artista_detectado = cancion_anterior.split(" - ")[0]
    elif "-" in cancion_anterior: artista_detectado = cancion_anterior.split("-")[0]
         
    if artista_detectado and len(artista_detectado) > 2:
        print(f"🤖 AUTOPILOTO: Buscando 3 de '{artista_detectado}'...")
        exito, tit, lista_archivos = descargar_cancion(artista_detectado, es_automatico=True, ignorar_repetidas=False)
        
        if exito and lista_archivos:
            for arch in lista_archivos:
                cola_ia.append(arch) 
            print(f"✅ AUTOPILOTO AGREGÓ {len(lista_archivos)} A SU COLA")
            return True
    return False

def actualizar_programacion():
    global estado_radio, cola_humanos, cola_ia, cancion_pendiente_post_intro, en_proceso_de_cambio, ultimo_anuncio_hora
    
    tiempo_actual = time.time()
    if estado_radio["duracion_total"] > 0:
        if (tiempo_actual - estado_radio["hora_inicio_timestamp"]) < estado_radio["duracion_total"]: return

    if en_proceso_de_cambio: return 
    en_proceso_de_cambio = True
    print("🔄 CAMBIANDO PISTA...")

    try:
        if cancion_pendiente_post_intro:
            cancion, es_vip = cancion_pendiente_post_intro
            cancion_pendiente_post_intro = None
            titulo_clean = limpiar_titulo_pro(cancion)
            actualizar_historial_visual(cancion)
            
            titulo_mostrar = f"🌟 PEDIDO: {titulo_clean}" if es_vip else titulo_clean
            estado_radio.update({"archivo_actual": cancion, "titulo_actual": titulo_mostrar, "artista_actual": "Radio Sueño FM", "imagen_actual": buscar_portada_itunes(titulo_clean), "duracion_total": obtener_duracion(f"static/{cancion}"), "hora_inicio_timestamp": time.time()})
            return

        es_pedido_humano = bool(cola_humanos)
        
        if es_pedido_humano:
            cancion = cola_humanos.pop(0)
            es_pedido = True
        elif cola_ia:
            cancion = cola_ia.pop(0)
            es_pedido = False 
        else:
            cancion_anterior = estado_radio["archivo_actual"] if estado_radio["archivo_actual"] else ""
            lista_local = [f for f in os.listdir('static') if f.endswith('.mp3') and "voz_" not in f]
            lista_disponible = [f for f in lista_local if limpiar_titulo_pro(f) not in canciones_ya_sonadas]
            
            if not lista_disponible:
                if lista_local:
                    canciones_ya_sonadas.clear()
                    lista_disponible = lista_local
                else:
                    estado_radio["duracion_total"] = 5; estado_radio["hora_inicio_timestamp"] = time.time(); return

            cancion = random.choice(lista_disponible)
            es_pedido = False
            
            if cancion_anterior and "voz_" not in cancion_anterior:
                 threading.Thread(target=intentar_llenar_cola_inteligente, args=(cancion_anterior,)).start()

        
        portada = buscar_portada_itunes(limpiar_titulo_pro(cancion))
        ahora = datetime.now()
        minuto = ahora.minute
        
        tipo_intro = None
        es_hora_exacta = (minuto >= 0 and minuto <= 2) or (minuto >= 30 and minuto <= 32)
        marca_tiempo = f"{ahora.hour}-{'Media' if minuto >= 30 else 'Punto'}"
        
        if es_hora_exacta and estado_radio["ultimo_slot_anunciado"] != marca_tiempo:
            tipo_intro = "HORA"
            estado_radio["ultimo_slot_anunciado"] = marca_tiempo 
        elif not es_pedido and random.random() < 0.25:
            tipo_intro = "CURIOSO"
            
        if tipo_intro:
            texto = generar_presentacion_ia(cancion, tipo_intro)
            if texto:
                audio, dur = generar_voz(texto)
                cancion_pendiente_post_intro = (cancion, es_pedido)
                subtitulo = "Dando la hora..." if tipo_intro == "HORA" else "¿Sabías qué...?"
                estado_radio.update({"archivo_actual": audio, "titulo_actual": "🎙️ DJ SUEÑO", "artista_actual": subtitulo, "imagen_actual": portada, "duracion_total": dur, "hora_inicio_timestamp": time.time()})
            else:
                titulo_clean = limpiar_titulo_pro(cancion)
                actualizar_historial_visual(cancion)
                titulo_mostrar = f"🌟 PEDIDO: {titulo_clean}" if es_pedido else titulo_clean
                estado_radio.update({"archivo_actual": cancion, "titulo_actual": titulo_mostrar, "artista_actual": "Radio Sueño FM", "imagen_actual": portada, "duracion_total": obtener_duracion(f"static/{cancion}"), "hora_inicio_timestamp": time.time()})
        else:
            titulo_clean = limpiar_titulo_pro(cancion)
            actualizar_historial_visual(cancion)
            titulo_mostrar = f"🌟 PEDIDO: {titulo_clean}" if es_pedido else titulo_clean
            estado_radio.update({"archivo_actual": cancion, "titulo_actual": titulo_mostrar, "artista_actual": "Radio Sueño FM", "imagen_actual": portada, "duracion_total": obtener_duracion(f"static/{cancion}"), "hora_inicio_timestamp": time.time()})
            
    finally:
        en_proceso_de_cambio = False

if __name__ == '__main__':
    hostname = socket.gethostname()
    try:
        ip_local = socket.gethostbyname(hostname)
        print(f"\n📡 RADIO LIVE EN: http://{ip_local}:5000")
    except:
        print("\n📡 RADIO LIVE (Local)")
        
    actualizar_programacion()
    app.run(host='0.0.0.0', port=5000, debug=False)