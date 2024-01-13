import random
import cocotb
from coco_env.packet import Packet
from coco_env.bin_operation import countones
from coco_env.bin_operation import check_pos
from cocotb.triggers import RisingEdge

class AxisIf:
    def __init__(self, aclk, tdata, tvalid=None, tlast=None, tkeep=None, tuser=None, tready=None, sop=None, width=4):
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

    def __init__(self, name, axis_if, width = 4, tdata_unpack = 0):
        self.name = name
        self.axis_if = axis_if
        self.width = width
        self.tdata_unpack = tdata_unpack

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
                if word_num == len(pkt.data)-1 and pkt.pkt_size % self.width != 0:
                    self.axis_if.tkeep.value = (1 << (pkt.pkt_size % self.width))-1
                else:
                    self.axis_if.tkeep.value = (1 << (self.width))-1
            #TLAST generation
            if(self.axis_if.tlast is not None):
                if(word_num == len(pkt.data)-1):
                    self.axis_if.tlast.value = 1
            wr_data = pkt.data[word_num]
            if(self.tdata_unpack):
                wr_data_list = []
                for byte_indx in range(self.width):
                    wr_data_list.append(wr_data  >> (byte_indx * 8) & 0xFF)
                wr_data_list.reverse()
                self.axis_if.tdata.value = wr_data_list
            else:
                self.axis_if.tdata.value = wr_data
            if self.axis_if.tvalid is not None:
                self.axis_if.tvalid.value = 1
            await RisingEdge(self.axis_if.aclk)
            # If backpressure is enabled wait for TREADY to
            # send the next word.
            if(self.axis_if.tready is not None):
                if(self.axis_if.tready.value == 1):
                    word_num += 1
            else:
                word_num += 1
        if self.axis_if.tvalid is not None:
            self.axis_if.tvalid.value = 0
        if self.axis_if.tlast is not None:
            self.axis_if.tlast.value = 0

#----------------------------------------------
# Axis monitor. 
#----------------------------------------------

class AxisMonitor:
    def __init__(self, name, axis_if, aport, width = 4, tdata_unpack = 0):
        self.name    = name
        self.width   = width
        self.aport   = aport
        self.axis_if  = axis_if        
        self.data    = []
        self.tdata_unpack = tdata_unpack
        
    async def mon_if(self):
        # Handle unpacked TDATA        
        pkt_cntr = 1
        pkt_size = 0
        while(True):
            await RisingEdge(self.axis_if.aclk)
            if(self.axis_if.tready is None):
                tnx_completed = self.axis_if.tvalid.value
            else:
                tnx_completed = self.axis_if.tvalid.value and self.axis_if.tvalid.tready
            if(tnx_completed):
                if(self.tdata_unpack):
                    tdata_int = 0
                    indx = 0
                    for item in reversed(self.axis_if.tdata.value):                        
                        tdata_int = tdata_int | (item << indx*8)
                        indx += 1
                else:                    
                    tdata_int = self.axis_if.tdata.value.integer
                #####################
                # Tkeep handle
                # 1. Filter valid bytes only
                # 2. Accumulate the packet size
                #####################
                if self.axis_if.tkeep is not None:
                    tkeep_int = 0
                    pkt_size += countones(self.axis_if.tkeep.value)
                    for byte_indx in range(0, self.width):
                        if check_pos(self.axis_if.tkeep.value, byte_indx):
                            tkeep_int |= 0xFF << (8 * byte_indx)
                    tkeep_int = int(bin(tkeep_int)[:1:-1], 2)
                else:
                    tkeep_int = (2 ** self.width)-1
                    if(self.axis_if.tlast.value == 1):
                        # +1 since current word is still in process
                        pkt_size = self.width*(len(self.data)+1)                

                # Append only valid data
                self.data.append(tdata_int & tkeep_int)
                
                #####################
                # Last cycle
                #####################
                if(self.axis_if.tlast.value == 1):
                    pkt_mon = Packet(self.name, self.width)
                    pkt_mon.data = self.data.copy()
                    # Pkt size calculation:
                    pkt_mon.pkt_size = pkt_size
                    # Clear data
                    self.data = []
                    mon_str = f"[{self.name}] PACKET[{pkt_cntr}] INFO: \n"
                    pkt_mon.print_pkt(mon_str)
                    self.aport.append(pkt_mon)
                    pkt_cntr += 1
                    

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
                                
