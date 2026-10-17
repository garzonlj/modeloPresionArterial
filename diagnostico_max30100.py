import time
import smbus

I2C_BUS_NUM = 1
MAX30100_ADDR = 0x57

REG_INT_STATUS = 0x00
REG_FIFO_WR_PTR = 0x02
REG_OVF_COUNTER = 0x03
REG_FIFO_RD_PTR = 0x04
REG_MODE_CONFIG = 0x06
REG_SPO2_CONFIG = 0x07
REG_LED_CONFIG = 0x09
REG_PART_ID = 0xFF

MODE_SPO2 = 0x03

bus = smbus.SMBus(I2C_BUS_NUM)


def leer(reg):
    return bus.read_byte_data(MAX30100_ADDR, reg)


print("Part ID (deberia ser 0x11 en un MAX30100 genuino):", hex(leer(REG_PART_ID)))

bus.write_byte_data(MAX30100_ADDR, REG_MODE_CONFIG, 0x40)
time.sleep(0.1)
print("MODE_CONFIG tras reset:", hex(leer(REG_MODE_CONFIG)))

bus.write_byte_data(MAX30100_ADDR, REG_MODE_CONFIG, MODE_SPO2)
time.sleep(0.05)
print("MODE_CONFIG tras setear SPO2:", hex(leer(REG_MODE_CONFIG)))

value = (1 << 6) | (0x01 << 2) | 0x03
bus.write_byte_data(MAX30100_ADDR, REG_SPO2_CONFIG, value)
time.sleep(0.05)
print("SPO2_CONFIG:", hex(leer(REG_SPO2_CONFIG)))

bus.write_byte_data(MAX30100_ADDR, REG_LED_CONFIG, (0x08 << 4) | 0x08)
time.sleep(0.05)
print("LED_CONFIG:", hex(leer(REG_LED_CONFIG)))

print("\nMonitoreando FIFO_WR_PTR / FIFO_RD_PTR / OVF_COUNTER por 15 segundos...")
print("Pon el dedo sobre el sensor ahora. Si wr_ptr nunca cambia, el sensor no esta muestreando.\n")

inicio = time.time()
while time.time() - inicio < 15:
    wr = leer(REG_FIFO_WR_PTR)
    rd = leer(REG_FIFO_RD_PTR)
    ovf = leer(REG_OVF_COUNTER)
    ints = leer(REG_INT_STATUS)
    print(f"wr_ptr={wr} rd_ptr={rd} ovf={ovf} int_status={bin(ints)}")
    time.sleep(0.5)
