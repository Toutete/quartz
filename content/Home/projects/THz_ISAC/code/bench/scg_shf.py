import time
import struct
import os
import sys
import pyvisa as visa
sys.path.append("C:\\Users\\Sooyeon Kim\\PycharmProjects\\20190129_ijl_osc")

#############################################################################
class scg_shf: #Class for control SHF 78120B signal clock generator.
#############################################################################
	def __init__(self, visa, name='78120B', interface='rs232', address=19, port=7):
# gpib device name# interface type ['gpib','rs232', 'tcpip', 'usb']# gpib address(integer) or tcpip address(string) #COM port or tcpip address (integer)
		self.name = name
		if interface == 'gpib':
			self.rm = visa
			#rm.list_resources()
			self.interface = self.rm.open_resource("GPIB0::%d::INSTR" % (address))
			self.tx_terminator = '\n'
			self.eol = ''

		if interface == 'usb':
			self.rm = visa
			#rm.list_resources()
			self.interface = self.rm.open_resource("USB0::0x0AAD::0x0092::101534::0::INSTR")
			self.tx_terminator = '\n'
			#self.tx_terminator = ';'
			self.eol = ''

		if interface == 'tcpip':
			self.rm = visa
			#rm.list_resources()
			#self.interface = self.rm.open_resource("TCPIP::192.168.0.200::0::INSTR") #TCPIP[board]::host address[::LAN device name][::INSTR]
			self.interface = self.rm.open_resource('TCPIP0::%s::%d::SOCKET' %(address,port))
			self.tx_terminator ='\n'
			#self.interface.timeout=20000
			self.eol = ''

		if interface == 'rs232':
			self.rm = visa
			self.interface = self.rm.open_resource('COM%d' %(port))
			self.tx_terminator ='\n'
			#self.tx_terminator =';'
			#self.interface.timeout=20000
			self.eol = ''
		#else:



#############################################################################
	def write(self, buf, max_n_try=10):
		buf = buf# + self.tx_terminator
		flag=0
		n_try=0
		while(flag==0):
			try :
				rsp=self.interface.write(buf)
				flag=1
			except Exception as e:
				print(f"Exception during write: {e}")
				flag=0
				n_try=n_try+1
				print('# %d of writing tried... but fail!' %(n_try)) 
			if(n_try>=max_n_try):
				flag=1
				print("I can't write data. Please check connection.")
				rsp="writing error"
		return rsp

#############################################################################
	def read(self, max_n_try=10):
		flag=0
		n_try=0
		while(flag==0):
			try :
				rsp=self.interface.read()
				flag=1
			except :
				flag=0
				n_try=n_try+1
				print('# %d of reading tried... but fail!' %(n_try)) 
				time.sleep(1)

			if(n_try>=max_n_try):
				flag=1
				print("I can't read data. Please check connection.")
				rsp="reading error"
		return rsp

#############################################################################
	def query(self):
		return self.interface.query()
#############################################################################
	def query2(self, cmd, max_n_try=2):
		flag=0
		n_try=0
		while(flag==0):
			try :
				self.write(cmd)
				rsp=self.interface.read()
				flag=1
			except :
				flag=0
				n_try=n_try+1
				print('# %d of reading tried... but fail!' %(n_try)) 
				time.sleep(1)

			if(n_try>=max_n_try):
				flag=1
				print("I can't read data. Please check connection.")
				rsp="query2 error"

		return rsp
#############################################################################
	def setfreq(self, freq=10200000000): #unit : GHz, MH, kHz, Hz
	#set the freq
		cmd = 'CLKSRC:FREQUENCY=%d;' % (freq)
		rsp=self.query2(cmd)
		return rsp

#############################################################################
	def getfreq(self):
	#get the frequency value
		cmd = "CLKSRC:FREQUENCY=?"
		tmp=self.query2(cmd)
		tmp=tmp.split('=')[-1]
		rsp=tmp.split(';')[0]
		return rsp
#############################################################################
	def setpower(self, power=-10):
		#set the power
		cmd = 'CLKSRC:AMPLITUDE=%.1f;' % (power)
		#print(cmd)
		rsp=self.query2(cmd)
		return rsp	
 #####################################################
	def getpower(self):
		#get the power value
		cmd = "CLKSRC:AMPLITUDE=?;"
		rsp=self.query2(cmd)
		return rsp
#############################################################################
	def on(self):
		#on#
		cmd ="CLKSRC:OUTPUT=ON;"
		rsp=self.query2(cmd)
		return rsp
#############################################################################
	def off(self):
		#off#
		cmd ="CLKSRC:OUTPUT=OFF;"
		rsp=self.query2(cmd)
		return rsp
#############################################################################
	def on_powerlimit(self):
		#on#
		cmd ="CLKSRC:POWERLIMIT=OVERRIDE:ON;"
		rsp=self.query2(cmd)
		return rsp
#############################################################################
	def off_powerlimit(self):
		#on#
		cmd ="CLKSRC:POWERLIMIT=OVERRIDE:OFF;"
		rsp=self.query2(cmd)
		return rsp
#############################################################################
