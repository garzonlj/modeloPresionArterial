
import code
import time
import smbus
import datetime

I2C_BUS_NUM = 1
REPORTING_PERIOD_S = 1.0

bus = smbus.SMBus(I2C_BUS_NUM)

MLX90614_ADDR = 0x5A
MLX90614_REG_TA = 0x06
MLX90614_REG_TOBJ1 = 0x07

TEMP_OFFSET_C = 1.481273


class MLX90614:
    def __init__(self, bus, address=MLX90614_ADDR):
        self.bus = bus
        self.address = address
        self.bus.read_word_data(self.address, MLX90614_REG_TA)

    def _read_temp(self, register):
        raw = self.bus.read_word_data(self.address, register)
        return (raw * 0.02) - 273.15

    def read_ambient(self):
        return self._read_temp(MLX90614_REG_TA)

    def read_object(self):
        return self._read_temp(MLX90614_REG_TOBJ1) + TEMP_OFFSET_C


MAX30100_ADDR = 0x57

REG_INT_STATUS = 0x00 # Estado de las interrupciones
REG_INT_ENABLE = 0x01 # Habilitación de interrupciones
REG_FIFO_WR_PTR = 0x02 # Puntero de escritura de la FIFO
REG_OVF_COUNTER = 0x03 # Contador de desbordamiento
REG_FIFO_RD_PTR = 0x04 # Puntero de lectura de la FIFO
REG_FIFO_DATA = 0x05 # Datos de la FIFO
REG_MODE_CONFIG = 0x06 # Configuración del modo
REG_SPO2_CONFIG = 0x07 # Configuración del SpO2
REG_LED_CONFIG = 0x09 # Configuración del LED
 
MODE_HR = 0x02 # Modo de frecuencia cardíaca
MODE_SPO2 = 0x03 # Modo de SpO2 


class MAX30100:
    def __init__(self, bus, address=MAX30100_ADDR, led_current_code=0x08):
        self.bus = bus
        self.address = address
        self._reset()
        self._set_mode(MODE_SPO2)
        self._set_spo2_config()
        self._set_led_current(led_current_code)

    #escribimos 0x40 en el registro de configuración para resetear el MAX30100
    def _reset(self):
        self.bus.write_byte_data(self.address, REG_MODE_CONFIG, 0x40)
        time.sleep(0.1)
    #esto es para configurar el modo de operación del MAX30100, en este caso modo SpO2
    def _set_mode(self, mode):
        self.bus.write_byte_data(self.address, REG_MODE_CONFIG, mode)

    #_set_spo2_config traduce esos dos parámetros humanos (sample_rate_bits, pulse_width_bits) 
    # a la representación binaria exacta que el chip espera, y la escribe con write_byte_data 
    # al registro REG_SPO2_CONFIG

    def _set_spo2_config(self, sample_rate_bits=0x01, pulse_width_bits=0x03):
        value = (1 << 6) | (sample_rate_bits << 2) | pulse_width_bits
        self.bus.write_byte_data(self.address, REG_SPO2_CONFIG, value)
        # coloca el código de tasa de muestreo en los bits 2-4. 0x01 según el datasheet = 100 muestras/segundo.

     #El registro de LED tiene dos campos de 4 bits: corriente del LED rojo (bits 4-7) y del LED IR (bits 0-3).
    # (code << 4) | code pone el mismo valor en ambos campos, es decir, misma intensidad para rojo e infrarrojo. 
    # code=0x08 es un nivel de corriente moderado (según tabla del datasheet, código 8 ≈ 24 mA).
    def _set_led_current(self, code):
        self.bus.write_byte_data(self.address, REG_LED_CONFIG, (code << 4) | code)

    #Compara puntero de escritura vs lectura de la FIFO (que tiene 16 posiciones y es circular) 
    # para saber cuántas muestras nuevas hay pendientes de leer
    def available_samples(self):
        wr_ptr = self.bus.read_byte_data(self.address, REG_FIFO_WR_PTR)
        rd_ptr = self.bus.read_byte_data(self.address, REG_FIFO_RD_PTR)
        return (wr_ptr - rd_ptr) % 16
    

    def read_sample(self):
        # Lee 4 bytes de datos de la FIFO: 2 bytes para IR y 2 bytes para rojo
        data = self.bus.read_i2c_block_data(self.address, REG_FIFO_DATA, 4)
        # Combina los bytes en enteros de 16 bits para IR y rojo
        ir = (data[0] << 8) | data[1]
        red = (data[2] << 8) | data[3]
        #DEVUELVE la cantidad de luz infrarroja y roja 
        # reflejada/transmitida por el dedo, medida por el fotodetector
        return ir, red

#Concepto: PPG (fotopletismografía)
#Cuando el corazón late, la sangre pulsa en los capilares del dedo, 
# cambiando ligeramente cuánta luz absorbe. La señal que capta el 
# sensor tiene dos componentes:

#DC (componente continua): el nivel base de luz, casi constante, 
# dominado por tejido, hueso, sangre venosa. Cambia muy lento.
#AC (componente alterna): la pequeña variación rítmica causada 
# por el pulso de sangre arterial con cada latido. Esta es la señal 
# útil.

class SignalProcessor:
    def __init__(self):
        self.ir_dc = None
        self.red_dc = None
        self.ir_ac_hist = []
        self.red_ac_hist = []
        self.ac_max_recent = 50
        self.last_beat_time = 0.0
        self.beat_intervals = []
        self.bpm_smooth = 0.0
        self.spo2_smooth = 0.0
        self.armed = True
        self.below_count = 0

    def process(self, ir, red):


        #Un EMA (Exponential Moving Average / media móvil exponencial) 
        # es una forma simple de suavizar una señal dejando pasar solo 
        # cambios lentos. La fórmula dc = dc + alpha*(nuevo - dc) mueve el
        #  promedio dc un poquito (3%, alpha_dc=0.03) hacia el valor nuevo
        #  cada vez. Como el pulso cardíaco cambia rápido pero el nivel base
        #  cambia lento, esto separa DC de AC: el filtro sigue el nivel base, 
        # y ir - dc deja solo la parte rápida/pulsátil.
        alpha_dc = 0.03
        if self.ir_dc is None:
            self.ir_dc = ir
            self.red_dc = red
        else:
            self.ir_dc = self.ir_dc + alpha_dc * (ir - self.ir_dc)
            self.red_dc = self.red_dc + alpha_dc * (red - self.red_dc)

        ir_ac = ir - self.ir_dc
        red_ac = red - self.red_dc

        # Guardamos los valores AC en un historial para 
        # calcular la amplitud máxima reciente

        self.ir_ac_hist.append(ir_ac)
        self.red_ac_hist.append(red_ac)
        if len(self.ir_ac_hist) > 300: #VENTANA DESLIZANTE DE 300 MUESTRAS
            self.ir_ac_hist.pop(0) 
            #pop(0) quita la más antigua para que 
            #la lista no crezca indefinidamente 
            self.red_ac_hist.pop(0)


        #Toma las últimas 20 muestras y calcula su "amplitud" (máximo menos mínimo) 
        #una medida rápida de qué tan grande está siendo la oscilación del pulso en 
        # este momento.
        #Suaviza esa amplitud con otro EMA (esta vez más rápido, 70% peso al valor 
        # nuevo) para tener ac_max_recent, una estimación estable de "qué tan grande 
        # es normalmente el pulso ahora" (se adapta si el dedo se mueve o si la señal
        #  es más débil/fuerte).
        #max(..., 30) evita que el umbral caiga a valores ridículamente bajos (piso 
        # mínimo de 30) cuando casi no hay señal, lo que evitaría detectar ruido 
        # como si fueran latidos.

        if len(self.ir_ac_hist) >= 20:
            recent = self.ir_ac_hist[-20:]
            local_amp = max(recent) - min(recent)
            self.ac_max_recent = max(0.3 * self.ac_max_recent + 0.7 * local_amp, 30)

        #threshold = 0.55 * ac_max_recent — el umbral para considerar "esto es un 
        # latido" es 55% de la amplitud típica reciente. Es un umbral adaptativo, 
        # no un número fijo, porque la señal cambia de persona a persona y de 
        # momento a momento.
        threshold = 0.55 * self.ac_max_recent
        now = time.time()

        #Para"rearmar, la señal debe bajar por debajo del 40% del umbral 
        # durante al menos 5 muestras consecutivas (below_count >= 5). 
        # Esto asegura que la señal realmente volvió a la línea base antes
        #  de buscar el siguiente pico — evita que ruido en la cresta del 
        # mismo latido se cuente como dos latidos.
        #Si en algún momento la señal sube de nuevo antes de completar 
        # 5 muestras seguidas por debajo, below_count se resetea a 0 
        #tiene que ser 5 muestras consecutivas.

        if not self.armed:
            if ir_ac < 0.4 * threshold:
                self.below_count += 1
                if self.below_count >= 5:
                    self.armed = True
            else:
                self.below_count = 0

        #Cuando la señal está "armada" y el valor AC infrarrojo supera el umbral,
        # y ha pasado al menos 0.33 segundos desde el último latido detectado
        # (para evitar falsos positivos por ruido), se registra un nuevo latido.
        # Se calcula el intervalo desde el último latido y se valida que esté dentro 
        # de un rango fisiológico (0.33 a 1.8 segundos).
        if self.armed and ir_ac > threshold and (now - self.last_beat_time) > 0.33:
            self.armed = False
            self.below_count = 0
            if self.last_beat_time > 0:
                interval = now - self.last_beat_time
                if 0.33 < interval < 1.8:
                    aceptar = True
                    #si ya hay al menos 3 intervalos previos, calcula la mediana de esos intervalos
                    #  y rechaza el nuevo intervalo si se desvía más del 40% de esa mediana. 
                    # Esto evita que un solo latido mal detectado (por ruido o movimiento)
                    #  distorsione el cálculo de BPM.
                    if len(self.beat_intervals) >= 3:
                        s = sorted(self.beat_intervals)
                        mediana = s[len(s) // 2]
                        if abs(interval - mediana) / mediana > 0.40:
                            aceptar = False
                    if aceptar:
                        self.beat_intervals.append(interval)
                        # Guarda hasta los últimos 8 intervalos
                        #  válidos (ventana deslizante nuevamente con pop(0)
                        if len(self.beat_intervals) > 8:
                            self.beat_intervals.pop(0)
            self.last_beat_time = now

    def get_bpm(self):
        #Si hay menos de 2 intervalos de latido registrados,
        #  devuelve el BPM suavizado actual (que podría ser 0 al inicio).
        if len(self.beat_intervals) < 2:
            return round(self.bpm_smooth)
        sorted_intervals = sorted(self.beat_intervals)
        median_interval = sorted_intervals[len(sorted_intervals) // 2]
        #60 segundos / intervalo en segundos = latidos por minuto.
        instant_bpm = 60.0 / median_interval
        if self.bpm_smooth == 0:
            self.bpm_smooth = instant_bpm
        else:
            #Suaviza el BPM instantáneo con un EMA (70% peso al valor previo, 30% al nuevo)
            self.bpm_smooth = 0.7 * self.bpm_smooth + 0.3 * instant_bpm
        return round(self.bpm_smooth)

    def get_spo2(self):
        #Si no hay suficientes datos (menos de 100 muestras AC) o 
        # si los valores DC son nulos, devuelve el SpO2 suavizado actual.
        if len(self.ir_ac_hist) < 100 or self.ir_dc in (None, 0) or self.red_dc in (None, 0):
            return round(self.spo2_smooth)

        #Calcula la raíz cuadrada de la media de los cuadrados (RMS) 
        # de las últimas 200 muestras AC
        # Esto da una medida de la amplitud de la señal AC para IR y rojo,
        # que luego se usa para calcular la relación R y estimar SpO2.
        window = 200
        ir_win = self.ir_ac_hist[-window:]
        red_win = self.red_ac_hist[-window:]

        ir_rms = (sum(v * v for v in ir_win) / len(ir_win)) ** 0.5
        red_rms = (sum(v * v for v in red_win) / len(red_win)) ** 0.5

        #Si la señal infrarroja es demasiado débil (dedo mal puesto, 
        # sensor sin contacto), no confía en el cálculo y devuelve el valor previo.
        if ir_rms < 15:
            return round(self.spo2_smooth)
        
        # Calcula la relación R = (AC_red/DC_red) / (AC_ir/DC_ir),
        # que es la base para estimar SpO2. La relación R refleja cómo
        # la absorción de luz roja e infrarroja cambia con la saturación
        #  de oxígeno en la sangre.
        # normaliza cada canal por su propio nivel base antes de compararlos, 
        # porque la magnitud absoluta de luz depende de cosas irrelevantes 
        # como el grosor del dedo o la intensidad del LED.

        R = (red_rms / self.red_dc) / (ir_rms / self.ir_dc)
        #110 - 25*R es una fórmula de calibración lineal empírica.
        instant_spo2 = 110 - 25 * R
        # Limita el SpO2 instantáneo a un rango fisiológico plausible (70% a 100%)
        #  para evitar valores absurdos por ruido o errores de medición.
        instant_spo2 = max(70, min(100, instant_spo2))

        if self.spo2_smooth == 0:
            self.spo2_smooth = instant_spo2
        else:
            #otro EMA para que la saturaciónd e oxigeno cambie de manera estable
            self.spo2_smooth = 0.85 * self.spo2_smooth + 0.15 * instant_spo2
        return round(self.spo2_smooth)


def main():
    print("Iniciando MLX90614...")
    try:
        mlx = MLX90614(bus)
        print("MLX90614 listo")
    except Exception as e:
        mlx = None
        print("Error: no se detectó el MLX90614 ->", e)

    print("Iniciando MAX30100...", end="")
    try:
        pox = MAX30100(bus)
        proc = SignalProcessor()
        print(" LISTO")
    except Exception as e:
        pox = None
        proc = None
        print(" FALLÓ ->", e)

    last_report = time.time()
    registros = []



    try:
        while True:
            if pox:
                # Lee todas las muestras disponibles en la FIFO del MAX30100
                #  y procesa cada par de valores IR y rojo.
                
                try:
                    n = pox.available_samples()
                    for _ in range(n):
                        ir, red = pox.read_sample()
                        # El procesador de señal toma los valores IR y rojo,
                        #  separa AC/DC, detecta latidos y calcula BPM y SpO2
                        proc.process(ir, red)
                except Exception as e:
                    print("Error leyendo MAX30100:", e)

            now = time.time()
            if now - last_report > REPORTING_PERIOD_S:
                # Lee la temperatura del objeto (cuerpo) desde el MLX90614 y
                #  obtiene BPM y SpO2 desde el procesador de señal.

                #nan si no hay sensor MLX90614 conectado, devuelve NaN para la temperatura.
                temp_objeto = mlx.read_object() if mlx else float("nan")
                # 0 para bpm y oxigeno
                bpm = proc.get_bpm() if proc else 0
                spo2 = proc.get_spo2() if proc else 0

                linea = (
                    f"Temp corporal: {temp_objeto:.2f} C | "
                    f"BPM: {bpm} | SpO2: {spo2}%"
                )
                print(linea)

                marca = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                registros.append(f"{marca} | {linea}")

                last_report = now

            time.sleep(0.005)

    except KeyboardInterrupt:
        print("\nFinalizado por el usuario")

    finally:
        if registros:
            nombre_archivo = datetime.datetime.now().strftime(
                "datos_sensores_%Y%m%d_%H%M%S.txt"
            )
            with open(nombre_archivo, "w") as f:
                f.write("\n".join(registros) + "\n")
            print(f"Datos guardados en {nombre_archivo}")


if __name__ == "__main__":
    main()
