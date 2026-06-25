import sys
import time
import binascii
from serial.tools import list_ports
import serial


def hexdump(b):
    if not b:
        return ""
    return ' '.join(f"0x{c:02X}" for c in b) + '   (' + ''.join((chr(c) if 32<=c<=126 else '.') for c in b) + ')'


def read_all(ser, timeout=1.0):
    end = time.time() + timeout
    data = bytearray()
    while time.time() < end:
        chunk = ser.read(ser.in_waiting or 1)
        if chunk:
            data.extend(chunk)
            # small pause to allow rest
            time.sleep(0.01)
        else:
            time.sleep(0.01)
    return bytes(data)


def main(port):
    print('Listing serial ports:')
    for p in list_ports.comports():
        print(p.device, '-', p.description, '-', p.hwid)

    print('\nProbing', port)
    try:
        ser = serial.Serial(port=port, baudrate=115200, timeout=0.5, write_timeout=0.5)
    except Exception as e:
        print('Open failed:', e)
        return

    try:
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        time.sleep(0.05)

        cmds = ["*IDN?", "IDN?", "READ?", "MEAS?", "PWR?", "ZERO", "CAL:ZERO", "SYST:ZERO", "INIT:ZERO"]
        for c in cmds:
            print('\n-> ASCII CMD:', c)
            try:
                ser.write((c + '\r').encode())
                ser.flush()
            except Exception as e:
                print('Write failed:', e)
                continue
            time.sleep(0.2)
            resp = read_all(ser, timeout=0.8)
            print('RESP:', hexdump(resp))

        # Try binary commands used by MATLAB
        bin_cmds = [bytes([ord('?'), ord('D'), ord('1'), 0,0,0,0,13]), bytes([ord('!'), ord('S'), ord('Z'),0,0,0,0,13]), bytes([ord('!'), ord('R'), ord('3'),0,0,0,0,13])]
        for b in bin_cmds:
            print('\n-> BINARY CMD:', hexdump(b))
            try:
                ser.write(b)
                ser.flush()
            except Exception as e:
                print('Write failed:', e)
                continue
            time.sleep(0.2)
            resp = read_all(ser, timeout=0.8)
            print('RESP:', hexdump(resp))

    finally:
        try:
            ser.close()
        except Exception:
            pass

if __name__ == '__main__':
    port = sys.argv[1] if len(sys.argv) > 1 else 'COM5'
    main(port)
