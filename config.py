# config.py
# Ustawienia sprzętowe
SERIAL_PORT = '/dev/ttyACM0'
BAUD = 115200
BUTTON_PIN, LED_PIN, BUZZER_PIN = 17, 27, 22

# Pliki bazowe
GML_FILE = 'Wybranowo-poprawione.gml'
GTX_FILE = 'geoida_PL.gtx'

# Parametry pomiaru
AVERAGING_EPOCHS = 10 

# NTRIP (Poprawki)
NTRIP_HOST, NTRIP_PORT, NTRIP_MOUNT = "91.198.76.2", 8080, "RTN4G_VRS_RTCM32"
NTRIP_USER, NTRIP_PASS = "kzlotnic", "Bartek1!!"
