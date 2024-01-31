import random
import cocotb
from coco_env.packet import Packet
from coco_env.bin_operation import countones
from coco_env.bin_operation import check_pos
from cocotb.triggers import RisingEdge

class AxisIf:
    def __init__(self, aclk, tdata, tvalid=None, tlast=None, tkeep=None, tuser=None, tready=None, width=4):
        self.aclk   = aclk
        self.tdata  = tdata
        self.tvalid = tvalid
        self.tkeep  = tkeep
        self.tlast  = tlast
        self.tuser  = tuser
        self.tready = tready
        self.width  = width
        
#----------------------------------------------
# Axis Driver.
#----------------------------------------------

class AxisDriver:

    def __init__(self, name, axis_if, width = 4, tdata_unpack = 0, msb_first = 0, flow_ctrl='always_on'):
        self.name         = name
        self.axis_if      = axis_if
        self.width        = width
        self.tdata_unpack = tdata_unpack
        self.msb_first    = msb_first
        self.flow_ctrl    = flow_ctrl

    async def send_pkt(self, pkt):
        pkt.check_pkt()
        tvalid_state = 1
        tvalid_val = 0
        for x in range(pkt.delay):
            await RisingEdge(self.axis_if.aclk)
        word_num = 0
        while word_num < len(pkt.data):
            #####################
            # TKEEP
            #####################
            if self.axis_if.tkeep is not None:
                if word_num == len(pkt.data)-1 and pkt.pkt_size % self.width != 0:
                    tkeep = (1 << (pkt.pkt_size % self.width))-1
                else:
                    tkeep = (1 << (self.width))-1
                    self.axis_if.tkeep.value = (1 << (self.width))-1
                if(self.msb_first):
                    tkeep = int(f"{tkeep:0{self.width}b}"[::-1],2)
                self.axis_if.tkeep.value = tkeep
            #####################
            # TLAST
            #####################
            if(self.axis_if.tlast is not None):
                if(word_num == len(pkt.data)-1):
                    self.axis_if.tlast.value = 1
            #####################
            # TDATA
            #####################
            wr_data = pkt.data[word_num]
            if(self.tdata_unpack):
                wr_data_list = []
                for byte_indx in range(self.width):
                    wr_data_list.append(wr_data  >> (byte_indx * 8) & 0xFF)
                if(self.msb_first == 0):
                    wr_data_list.reverse()
                self.axis_if.tdata.value = wr_data_list
            else:
                if(self.msb_first):
                    wr_data_rev = 0
                    for byte_indx in range(self.width):
                        wr_data_rev |= (wr_data  >> (byte_indx * 8) & 0xFF) << ((self.width-1-byte_indx)*8)
                    self.axis_if.tdata.value = wr_data_rev
                    wr_data = wr_data_rev
                self.axis_if.tdata.value = wr_data
            #####################
            # TVALID
            #####################
            if self.axis_if.tvalid is not None:
                if(self.flow_ctrl ==  'one_valid_one_nonvalid'):
                    if tvalid_state:
                        tvalid_state = 0
                    else:
                        tvalid_state = 1
                    self.axis_if.tvalid.value = tvalid_state
                elif(self.flow_ctrl == 'one_valid_some_nonvalid'):
                    if tvalid_state:
                        tvalid_val = 1                        
                        tvalid_delay = random.randint(1,5)
                        tvalid_state = 0
                    else:
                        tvalid_val = 0
                        if tvalid_delay:
                            tvalid_delay -= 1
                        else:
                            tvalid_state = 1
                    self.axis_if.tvalid.value = tvalid_val                        
                else:
                    self.axis_if.tvalid.value = 1

            #####################
            # TRANSACTION COMPLETION
            #####################
            await RisingEdge(self.axis_if.aclk)
            if(self.axis_if.tready is None):
                tnx_completed = self.axis_if.tvalid.value
            else:
                tnx_completed = self.axis_if.tvalid.value and self.axis_if.tvalid.tready
            if(tnx_completed):
                word_num += 1                
            
        if self.axis_if.tvalid is not None:
            self.axis_if.tvalid.value = 0
        if self.axis_if.tlast is not None:
            self.axis_if.tlast.value = 0
        tvalid_state = 1

#----------------------------------------------
# Axis monitor. 
#----------------------------------------------

class AxisMonitor:
    def __init__(self, name, axis_if, aport, width = 4, tdata_unpack = 0, msb_first=0):
        self.name    = name
        self.width   = width
        self.aport   = aport
        self.axis_if  = axis_if        
        self.data    = []
        self.tdata_unpack = tdata_unpack
        self.msb_first = msb_first
        
    async def mon_if(self):
        # Handle unpacked TDATA        
        pkt_cntr = 0
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
                    if(self.msb_first):
                        byte_range = range(self.width)
                    else:
                        byte_range = range(self.width)[::-1]
                    # TODO: add non-byte word.
                    for byte_indx in byte_range:
                        tdata_int = tdata_int | (self.axis_if.tdata.value[byte_indx] << indx*8)
                        indx += 1
                else:                    
                    tdata_int = self.axis_if.tdata.value.integer
                    tdata_rev = 0
                    for byte_indx in range(self.width):
                        tdata_rev |= (tdata_int  >> (byte_indx * 8) & 0xFF) << ((self.width-1-byte_indx)*8)
                    tdata_int = tdata_rev
                #####################
                # Tkeep handle
                # 1. Filter valid bytes only
                # 2. Accumulate the packet size
                #####################
                if self.axis_if.tkeep is not None:
                    tkeep_int = 0
                    pkt_size += countones(self.axis_if.tkeep.value)
                    print(f"pkt_size = {pkt_size}")
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
                    pkt_mon = Packet(f"{self.name}{pkt_cntr}", self.width)
                    pkt_mon.data = self.data.copy()
                    # Pkt size calculation:
                    pkt_mon.pkt_size = pkt_size
                    # Clear data
                    self.data = []
                    pkt_size = 0
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
                                
