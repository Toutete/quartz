import pyvisa
import time

def test_osa():
    rm = pyvisa.ResourceManager()
    inst = rm.open_resource("GPIB0::1::INSTR")
    inst.timeout = 5000
    inst.read_termination = '\r\n'
    inst.write_termination = '\r\n'
    
    inst.clear()
    
    inst.write("SGL")
    
    for i in range(20):
        try:
            # How to query sweep status?
            # Let's try SWEEP?, STB?, *STB?
            inst.write("SWEEP?")
            res = inst.read()
            print(f"SWEEP? returned: {res}")
        except Exception as e:
            print("SWEEP? failed:", e)
            
        time.sleep(1)
        
if __name__ == "__main__":
    test_osa()
