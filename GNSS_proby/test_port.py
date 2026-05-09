import serial
try:
    # Próbujemy otworzyć port
    ser = serial.Serial('/dev/ttyACM0', 115200, timeout=5)
    print("Port otwarty. Czekam na jakikolwiek bajt...")
    raw = ser.read(10) # Próba odczytu 10 bajtów
    if len(raw) > 0:
        print(f"SUKCES! Odebrano dane: {raw.hex()}")
    else:
        print("CISZA... u-blox nic nie wysyła.")
    ser.close()
except Exception as e:
    print(f"BŁĄD: {e}")
