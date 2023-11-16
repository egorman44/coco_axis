import random
import cocotb
from packet import Packet
from cocotb.triggers import RisingEdge
    
class axis_if:
    def __init__(self, aclk, tdata, tvalid, tkeep, tlast, tuser, tready, width=4):
        self.aclk = aclk
        self.tdata = tdata
        self.tvalid = tvalid
        self.tkeep = tkeep
        self.tlast = tlast
        self.tuser = tuser
        self.tready = tready
        self.width = width

#----------------------------------------------
# Axis Driver.
#----------------------------------------------

class axis_drv:

    def __init__(self, axis_if):
        self.axis_if = axis_if

    async def send_pkt(self, pkt):
        pkt.check_pkt()
        for x in range(pkt.delay):
            await RisingEdge(self.axis_if.aclk)
        word_num = 0
        while word_num < len(pkt.data):
            #EOP generation
            if(word_num == len(pkt.data)-1):
                self.axis_if.tlast.value = 1                            
            self.axis_if.tdata.value = pkt.data[word_num]
            self.axis_if.tvalid.value = 1
            await RisingEdge(self.axis_if.aclk)
            if(self.axis_if.tready.value == 1):
                word_num += 1
        self.axis_if.tvalid.value = 0
        self.axis_if.tlast.value = 0

#----------------------------------------------
# Axis monitor. 
#----------------------------------------------

class axis_mon:
    def __init__(self, axis_if, aport, width = 4, corrupt = 0):
        self.width   = width
        self.aport   = aport
        self.axis_if = axis_if        
        self.data    = []
        self.corrupt = corrupt
        
    async def mon_if(self):            
        while(True):
            await RisingEdge(self.axis_if.aclk)
            if(self.axis_if.tvalid.value == 1 and self.axis_if.tready.value == 1):
                self.data.append(self.axis_if.tdata.value.integer)
                if(self.axis_if.tlast.value == 1):
                    # Intentionally corrupt the packet                    
                    if(self.corrupt):
                        corr_word_pos   = random.randint(0,len(self.data))
                        corr_bit_pos    = random.randint(0,self.width*8)
                        corr_data       = 1 << corr_bit_pos
                        self.data[corr_word_pos] = self.data[corr_word_pos] ^ corr_data
                    pkt_mon = Packet(self.width)
                    pkt_mon.data = self.data.copy()
                    # Clear data
                    self.data = []
                    pkt_mon.print_pkt()
                    self.aport.append(pkt_mon)
                    

#----------------------------------------------
# Axis responder. Control TREADY signal.
#----------------------------------------------

class axis_rsp:

    def __init__(self, axis_if, behaviour = 'ALWAYS_READY'):
        self.axis_if = axis_if
        self.behaviour = behaviour

    async def tready_ctrl(self):
        if(self.behaviour == 'ALWAYS_READY'):
            self.axis_if.tready.value = 1
        elif(self.behaviour == 'BACKPRESSURE_1'):
            while True:
                self.axis_if.tready.value = 1
                await RisingEdge(self.axis_if.tvalid)
                await RisingEdge(self.axis_if.aclk)
                self.axis_if.tready.value = 0
                for cycle_num in range(0,5):
                    await RisingEdge(self.axis_if.aclk)
        elif(self.behaviour == 'BACKPRESSURE_1'):
            while True:
                self.axis_if.tready.value = 1
                await RisingEdge(self.axis_if.tvalid)
                await RisingEdge(self.axis_if.aclk)
                self.axis_if.tready.value = 0
                for cycle_num in range(0,5):
                    await RisingEdge(self.axis_if.aclk)
        else:
            assert False, "[ERROR] axis_rsp behaviour is not set."
                                
