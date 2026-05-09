import serial
from pyubx2 import UBXMessage

# Otwieramy port
ser = serial.Serial('/dev/ttyACM0', 115200, timeout=1)

# Dodaliśmy '1' po nazwie wiadomości - to oznacza tryb SET (ustawianie)
msg = UBXMessage("CFG", "CFG-MSG", 1, msgClass=0x01, msgID=0x07, rateUSB=1)

print("Wysyłam komendę aktywacji UBX-NAV-PVT...")
ser.write(msg.serialize())
print("Gotowe! Teraz u-blox powinien zacząć wysyłać dane binarne.")
ser.close()
