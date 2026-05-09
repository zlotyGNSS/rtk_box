import serial
import socket
import base64
import time

# --- KONFIGURACJA (Sprawdź dwa razy!) ---
SERIAL_PORT = '/dev/ttyACM0'
BAUD = 115200
NTRIP_HOST = "91.198.76.2" 
NTRIP_PORT = 8080
NTRIP_MOUNT = "RTN4G_VRS_RTCM32"
NTRIP_USER = "kzlotnic"
NTRIP_PASS = "Bartek1!!"

# Ramka pozycji do testu
FAKE_GGA = "$GPGGA,120000,5251.000,N,01743.000,E,1,12,1.0,100.0,M,33.0,M,,*6E\r\n"

def test_system():
    print("=== TEST DIAGNOSTYCZNY RTK v7 ===")
    
    # 1. TEST PORTU SZEREGOWEGO
    print(f"\n[1/2] Testowanie portu {SERIAL_PORT}...")
    try:
        ser = serial.Serial(SERIAL_PORT, BAUD, timeout=3)
        print(f"      [OK] Port {SERIAL_PORT} otwarty.")
        
        print("      Czekam 5 sekund na dane z u-bloxa...")
        raw_data = ser.read(100)
        if len(raw_data) > 0:
            print(f"      [SUKCES] Odebrano {len(raw_data)} bajtów z u-bloxa!")
            print(f"      Nagłówek danych: {raw_data[:20].hex()}")
        else:
            print("      [BŁĄD] Port otwarty, ale u-blox NIC nie wysyła. Sprawdź kabel!")
        ser.close()
    except Exception as e:
        print(f"      [KRYTYCZNY BŁĄD PORTU]: {e}")

    # 2. TEST NTRIP
    print(f"\n[2/2] Testowanie połączenia NTRIP z {NTRIP_HOST}...")
    try:
        auth = base64.b64encode(f"{NTRIP_USER}:{NTRIP_PASS}".encode()).decode()
        sock = socket.create_connection((NTRIP_HOST, NTRIP_PORT), timeout=10)
        
        headers = (f"GET /{NTRIP_MOUNT} HTTP/1.0\r\n"
                   f"User-Agent: NTRIP-Tester\r\n"
                   f"Authorization: Basic {auth}\r\n"
                   f"Connection: close\r\n\r\n")
        
        sock.sendall(headers.encode())
        sock.sendall(FAKE_GGA.encode())
        
        print("      Wysłano zapytanie i pozycję GGA. Czekam na odpowiedź...")
        
        # Próba odebrania pierwszych poprawek
        data = sock.recv(1024)
        if data:
            if b"ICY 200 OK" in data or len(data) > 20:
                print(f"      [SUKCES] Serwer NTRIP wysyła poprawki! (Odebrano: {len(data)} bajtów)")
            else:
                print(f"      [PROBLEM] Serwer odpowiedział, ale nie przesyła danych: {data[:50]}")
        else:
            print("      [BŁĄD] Serwer połączył, ale nic nie wysłał.")
        sock.close()
    except Exception as e:
        print(f"      [BŁĄD NTRIP]: {e}")

if __name__ == "__main__":
    test_system()
