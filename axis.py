# TODO check the type of tdata to define it's type and get rid off tdata_unpack
import random
import cocotb
import math
from coco_env.packet import Packet
from coco_env.bin_operation import countones
from coco_env.bin_operation import check_pos
from cocotb.triggers import RisingEdge
from cocotb.utils import get_sim_time
class AxisIf:
    def __init__(self, aclk, tdata, width, unpack, tvalid=None, tlast=None, tkeep=None, tuser=None, tready=None, tkeep_type='packed'):
        self.aclk   = aclk
        self.tdata  = tdata
        self.tvalid = tvalid
        self.tkeep  = tkeep
        self.tlast  = tlast
        self.tuser  = tuser
        self.tready = tready
        self.width  = width
        self.unpack = unpack
        self.tkeep_type = tkeep_type
        
#----------------------------------------------
# Axis Driver.
#----------------------------------------------

# TODO: get width out of axis_if

class AxisDriver:

    def __init__(self, name, axis_if, msb_first = 0, flow_ctrl='always_on'):
        self.name      = name
        self.axis_if   = axis_if
        self.width     = axis_if.width
        self.unpack    = axis_if.unpack
        self.msb_first = msb_first
        self.flow_ctrl = flow_ctrl

    async def send_pkt(self, pkt):
        pkt.check_pkt()
        word_list = pkt.get_word_list(self.width)
        tvalid_state = 1
        tvalid_val = 1
        tvalid_delay = random.randint(1,5)
        for x in range(pkt.delay):
            await RisingEdge(self.axis_if.aclk)
        word_num = 0
        pkt_len_in_words = math.ceil(pkt.pkt_size/self.width)
        while word_num < pkt_len_in_words:
            #####################
            # TKEEP
            #####################
            if self.axis_if.tkeep is not None:
                if word_num == pkt_len_in_words-1 and pkt.pkt_size % self.width != 0:
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
                if(word_num == pkt_len_in_words-1):
                    self.axis_if.tlast.value = 1
            #####################
            # TDATA
            #####################
            wr_data = word_list[word_num]
            if(self.unpack == 'unpacked'):
                wr_data_list = []
                for byte_indx in range(self.width):
                    wr_data_list.append(wr_data  >> (byte_indx * 8) & 0xFF)
                if(self.msb_first == 0):
                    wr_data_list.reverse()
                self.axis_if.tdata.value = wr_data_list
            elif(self.unpack == 'packed'):
                if(self.msb_first):
                    wr_data_rev = 0
                    for byte_indx in range(self.width):
                        wr_data_rev |= (wr_data  >> (byte_indx * 8) & 0xFF) << ((self.width-1-byte_indx)*8)
                    self.axis_if.tdata.value = wr_data_rev
                    wr_data = wr_data_rev
                self.axis_if.tdata.value = wr_data
            else:
                assert False , f"[BAD_CONFIG] AXIS driver tdata in wrong format"
            #####################
            # TVALID
            #####################
            if self.axis_if.tvalid is not None:
                if(self.flow_ctrl == 'flow_en'):
                    self.flow_ctrl = random.choice(['one_valid_one_nonvalid', 'one_valid_some_nonvalid', 'some_valid_some_nonvalid'])
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
                elif(self.flow_ctrl == 'some_valid_some_nonvalid'):
                    if tvalid_delay:
                        tvalid_delay -= 1
                    else:
                        tvalid_delay = random.randint(1,5)
                        tvalid_val = tvalid_val ^ 1
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
    def __init__(self, name, axis_if, aport=None, msb_first=0, static_pkt=None):
        self.name      = name
        self.aport     = aport
        self.axis_if   = axis_if
        self.width     = axis_if.width        
        self.data      = []
        self.unpack    = axis_if.unpack
        self.msb_first = msb_first
        self.static_pkt = static_pkt
        self.pkt_size = 0
        self.pkt_cntr = 0
        
    async def mon_if(self):
        # Handle unpacked TDATA        
        
        while(True):
            await RisingEdge(self.axis_if.aclk)
            if(self.axis_if.tready is None):
                tnx_completed = self.axis_if.tvalid.value
            else:
                tnx_completed = self.axis_if.tvalid.value and self.axis_if.tvalid.tready
            if(tnx_completed):
                if(self.unpack == 'unpacked'):
                    tdata_int = 0
                    indx = 0
                    if(self.msb_first):
                        byte_range = range(self.width)
                    else:
                        byte_range = range(self.width)[::-1]
                    # TODO: add non-byte word. Do we need it ?! 
                    for byte_indx in byte_range:
                        tdata_int = tdata_int | (self.axis_if.tdata.value[byte_indx] << indx*8)
                        indx += 1                        
                elif(self.unpack == 'packed'):                    
                    tdata_int = self.axis_if.tdata.value.integer
                    if(self.width > 1):
                        tdata_rev = 0
                        for byte_indx in range(self.width):
                            tdata_rev |= (tdata_int  >> (byte_indx * 8) & 0xFF) << ((self.width-1-byte_indx)*8)
                    else:
                        tdata_rev = tdata_int                    
                    tdata_int = tdata_rev
                elif(self.unpack == 'chisel_vec'):
                    tdata_int = 0
                    indx = 0
                    byte_range = range(self.width)
                    # TODO: add non-byte word. Do we need it ?! 
                    for byte_indx in byte_range:
                        tdata_int = tdata_int | (self.axis_if.tdata[byte_indx].value << indx*8)
                        indx += 1
                else:
                    assert False , f"[BAD_CONFIG] AXIS monitor tdata in wrong format"
                #####################
                # Tkeep handle
                # 1. Filter valid bytes only
                # 2. Accumulate the packet size
                #####################
                if self.axis_if.tkeep is not None:
                    if(self.axis_if.tkeep_type == 'packed'):
                        tkeep_int_val = self.axis_if.tkeep.value
                    elif(self.axis_if.tkeep_type == 'chisel_vec'):
                        tkeep_int_val = 0
                        for i in range(len(self.axis_if.tkeep)):
                            tkeep_int_val |= self.axis_if.tkeep[i].value << i
                    print(f"tkeep_int_val={tkeep_int_val}")
                    tkeep_int = 0
                    self.pkt_size += countones(tkeep_int_val)
                    for byte_indx in range(0, self.width):
                        if check_pos(tkeep_int_val, byte_indx):
                            tkeep_int |= 0xFF << (8 * byte_indx)
                        tkeep_int = int(bin(tkeep_int)[:1:-1], 2)                        
                else:
                    tkeep_int = (2 ** (8*self.width))-1
                    self.pkt_size += self.width
                    
                # Append only valid data
                self.data.append(tdata_int & tkeep_int)
                
                #####################
                # Last cycle
                #####################
                if self.axis_if.tlast is not None:
                    if self.axis_if.tlast.value == 1:
                        self.write_aport()
                else:
                    if self.static_pkt is not None:
                        if self.static_pkt <= self.pkt_size:
                            self.write_aport()


            #####################
            # send packet 
            #####################
    def write_aport(self):
        pkt_mon = Packet(f"{self.name}-{self.pkt_cntr}")
        pkt_mon.write_word_list(self.data, self.pkt_size, self.width)                       
        # Clear data
        self.data = []
        self.pkt_size = 0
        mon_str = f"[{self.name}] PACKET[{self.pkt_cntr}] INFO: \n"
        pkt_mon.print_pkt(mon_str)
        time_ns = get_sim_time(units='ns')
        print(f"time= {time_ns}")
        self.aport.append(pkt_mon)
        self.pkt_cntr += 1
        

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
                                
