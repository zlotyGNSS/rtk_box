# config.py - v33 Master Quality
SERIAL_PORT = '/dev/ttyACM0'
BAUD = 115200

# Pliki danych
GML_FILE = 'Wybranowo-poprawione.gml'
GTX_FILE = 'geoida_PL.gtx'

# Parametry pomiaru v33
AVERAGING_EPOCHS = 15      # Czas uśredniania (sekundy)
SIGMA_LIMIT = 2.0          # Granica błędu w cm (powyżej tego pomiar jest "niepewny")

# Sprzęt (Piny)
BUTTON_PIN, LED_PIN, BUZZER_PIN = 17, 27, 22

# NTRIP (Poprawki)
NTRIP_HOST, NTRIP_PORT, NTRIP_MOUNT = "91.198.76.2", 8080, "RTN4G_VRS_RTCM32"
NTRIP_USER, NTRIP_PASS = "kzlotnic", "Bartek1!!"
