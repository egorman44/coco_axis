import random
import cocotb
from coco_env.packet import Packet
from coco_env.bin_operation import countones
from cocotb.triggers import RisingEdge

class AxisIf:
    def __init__(self, aclk, tdata, tvalid, tlast, tkeep=None, tuser=None, tready=None, sop=None, width=4):
        self.aclk   = aclk
        self.tdata  = tdata
        self.tvalid = tvalid
        self.tkeep  = tkeep
        self.tlast  = tlast
        self.tuser  = tuser
        self.sop    = sop
        self.tready = tready
        self.width  = width
        
#----------------------------------------------
# Axis Driver.
#----------------------------------------------

class AxisDriver:

    def __init__(self, name, axis_if, width = 4):
        self.name = name
        self.axis_if = axis_if
        self.width = width

    async def send_pkt(self, pkt):
        pkt.check_pkt()
        for x in range(pkt.delay):
            await RisingEdge(self.axis_if.aclk)
        word_num = 0
        while word_num < len(pkt.data):
            #SOP generation
            if self.axis_if.sop is not None:
                if(word_num == 0):
                    self.axis_if.sop.value = 1
                else:
                    self.axis_if.sop.value = 0
            #TKEEP generation
            if self.axis_if.tkeep is not None:
                if(word_num == len(pkt.data)-1):
                    self.axis_if.tkeep.value = (1 << (pkt.pkt_size % self.width))-1
                else:
                    self.axis_if.tkeep.value = (1 << (self.width))-1
            #TLAST generation
            if(word_num == len(pkt.data)-1):
                self.axis_if.tlast.value = 1
            self.axis_if.tdata.value = pkt.data[word_num]
            self.axis_if.tvalid.value = 1
            await RisingEdge(self.axis_if.aclk)
            # If backpressure is enabled wait for TREADY to
            # send the next word.
            if(self.axis_if.tready is not None):
                if(self.axis_if.tready.value == 1):
                    word_num += 1
            else:
                word_num += 1
        self.axis_if.tvalid.value = 0
        self.axis_if.tlast.value = 0

#----------------------------------------------
# Axis monitor. 
#----------------------------------------------

class AxisMonitor:
    def __init__(self, name, axis_if, aport, width = 4, corrupt = 0):
        self.name    = name
        self.width   = width
        self.aport   = aport
        self.axis_if  = axis_if        
        self.data    = []
        self.corrupt = corrupt
        
    async def mon_if(self):
        pkt_cntr = 1
        while(True):
            await RisingEdge(self.axis_if.aclk)
            if(self.axis_if.tready is None):
                tnx_completed = self.axis_if.tvalid.value
            else:
                tnx_completed = self.axis_if.tvalid.value and self.axis_if.tvalid.tready
            if(tnx_completed):
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
                    # Pkt size calculation:
                    pkt_mon.pkt_size = self.calc_pkt_size()                    
                    # Clear data
                    self.data = []
                    mon_str = f"[{self.name}] PACKET[{pkt_cntr}] INFO: \n"
                    pkt_mon.print_pkt(mon_str)
                    self.aport.append(pkt_mon)
                    pkt_cntr += 1

    def calc_pkt_size(self):
        # If TKEEP is not conencted then treat all
        # words as full
        if self.axis_if.tkeep is not None:
            pkt_size = self.width*(len(self.data)-1) + countones(self.axis_if.tkeep.value)
        else:
            pkt_size = self.width*(len(self.data))
        return pkt_size
                    

#----------------------------------------------
# Axis responder. Control TREADY signal.
#----------------------------------------------

class AxisResponder:

    def __init__(self, name, axis_if, behaviour = 'ALWAYS_READY'):
        self.name = name
        self.axis_if = axis_if
        self.behaviour = behaviour

    async def tready_ctrl(self):
        if(self.behaviour == 'ALWAYS_READY'):
            self.axis_if.tready.value = 1
        elif(self.behaviour == 'BACKPRESSURE_1'):
            while True:
                self.axis_if.tready.value = 1
                if self.axis_if.tvalid.value == 0:
                    await RisingEdge(self.axis_if.tvalid)
                await RisingEdge(self.axis_if.aclk)
                self.axis_if.tready.value = 1
                interval = random.randint(1,5)
                for cycle_num in range(0,interval):
                    await RisingEdge(self.axis_if.aclk)
                self.axis_if.tready.value = 0
                interval = random.randint(1,5)
                for cycle_num in range(0,interval):
                    await RisingEdge(self.axis_if.aclk)                        
        elif(self.behaviour == 'BACKPRESSURE_0'):
            while True:
                self.axis_if.tready.value = 1
                await RisingEdge(self.axis_if.tvalid)
                await RisingEdge(self.axis_if.aclk)
                self.axis_if.tready.value = 0
                for cycle_num in range(0,5):
                    await RisingEdge(self.axis_if.aclk)
        else:
            assert False, "[ERROR] AxisResponder behaviour is not set."
                                
