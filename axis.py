# TODO check the type of tdata to define it's type and get rid off tdata_unpack
import random
import cocotb
import math
from packet import Packet
from bin_operation import countones
from bin_operation import check_pos
from cocotb.triggers import RisingEdge
from cocotb.utils import get_sim_time

class AxisIf:
    def __init__(self, aclk, tdata, width, unpack, tvalid=None, tlast=None, tkeep=None, tuser=None, tready=None, tkeep_type='packed', uwidth=None):
        self.aclk   = aclk
        self.tdata  = tdata
        self.tvalid = tvalid
        self.tkeep  = tkeep
        self.tlast  = tlast
        self.tuser  = tuser
        self.tready = tready
        self.width  = width
        self.uwidth  = uwidth
        self.unpack = unpack
        self.tkeep_type = tkeep_type        

'''
AxisDriver
'''

class AxisDriver:

    '''
    pkt0_word0 - defines where packet first byte is mapped. 
    If pkt0_word0 = 1, then packet[0] is mapped into TDATA[0]
    If pkt0_word0 = 0, then packet[0] is mapped into TDATA[self.width-1]
    '''

    def __init__(self, name, axis_if, pkt0_word0 = 1, flow_ctrl='always_on'):
        self.name      = name
        self.axis_if   = axis_if
        self.width     = axis_if.width
        self.unpack    = axis_if.unpack
        self.pkt0_word0 = pkt0_word0
        self.flow_ctrl = flow_ctrl
        self.print_cfg()

    
    def print_cfg(self):
        print(f"\n\t DRIVER_CFG")
        print(f"\t\t DRIVER_NAME : {self.name}")
        print(f"\t\t WIDTH       : {self.width}")
        print(f"\t\t UNPACK      : {self.unpack}")
        print(f"\t\t PKT0_WORD0  : {self.pkt0_word0}")
        print(f"\t\t FLOW_CTRL   : {self.flow_ctrl}")

    '''
    Functions that controlls different ports of AXIS interface
    '''
    def check_transaction_completion(self):
        if(self.axis_if.tready is None):
            if self.axis_if.tvalid is not None:
                tnx_completed = self.axis_if.tvalid.value
            else:
                tnx_completed = 1
        else:
            tnx_completed = self.axis_if.tvalid.value and self.axis_if.tready.value
        return tnx_completed
        
    def drive_tlast(self, last_word):
        if(self.axis_if.tlast is not None):
            if(last_word):
                self.axis_if.tlast.value = 1
            else:
                self.axis_if.tlast.value = 0

    def drive_tuser(self, pkt, last_word):
        if(self.axis_if.tuser is not None):
            if(last_word):
                self.axis_if.tuser.value = pkt.user[0]
            else:
                self.axis_if.tuser.value = pkt.user[0]

    def drive_tkeep(self, pkt, last_word):
        if self.axis_if.tkeep is not None:
            if last_word and pkt.pkt_size % self.width != 0:
                tkeep_msb_pos = pkt.pkt_size % self.width
            else:
                tkeep_msb_pos = self.width
            if self.axis_if.tkeep_type == 'ffs':
                tkeep = 1 << (tkeep_msb_pos-1)
            elif self.axis_if.tkeep_type == 'packed':
                tkeep = (1 << tkeep_msb_pos)-1
            if(self.pkt0_word0==0):
                tkeep = int(f"{tkeep:0{self.width}b}"[::-1],2)
            self.axis_if.tkeep.value = tkeep

    def drive_tdata(self, pkt, last_word, word_num):
        # TODO: check that Endianess is matched for all combinations
        # Prepare data. Put it into the list
        data_list = [0] * self.width
        if(last_word):
            data_list = pkt.data[self.width*word_num:]
        else:            
            data_list = pkt.data[self.width*word_num:self.width*(word_num+1)]
        # append if last cycle and data < self.width
        if(len(data_list) < self.width):
            data_list = data_list + [0]*(self.width-len(data_list))
        # If DUT port is unpacked array then COCOtb reverts
        # the list of the signals.
        if(self.unpack == 'unpacked'):
            if self.pkt0_word0 == 1:
                data_list.reverse()
            else:
                pass            
        elif self.unpack == 'chisel_vec':
            if self.pkt0_word0 == 0:
                data_list.reverse()
            else:
                pass
        elif self.unpack == 'packed':
            if self.pkt0_word0 == 1:
                pass
            else:
                data_list.reverse()
        else:
            if self.pkt0_word0 == 1:
                data_list.reverse()
        # Write data into IF in depends on the interface type
        if(self.unpack == 'unpacked'):
            self.axis_if.tdata.value = data_list
        elif(self.unpack == 'packed'):
            wr_data_int = 0
            for byte_indx in range(self.width):
                wr_data_int |= data_list[byte_indx] << (byte_indx * 8)
            self.axis_if.tdata.value = wr_data_int
        elif(self.unpack == 'chisel_vec'):
            for byte_indx in range(len(data_list)):
                self.axis_if.tdata[byte_indx].value = data_list[byte_indx]
        else:
            assert False , f"[BAD_CONFIG] AXIS driver tdata in wrong format"

    def drive_tvalid(self, tnx_completed):
        if self.axis_if.tvalid is not None:
            if(self.flow_ctrl == 'flow_en'):
                self.flow_ctrl = random.choice(['one_valid_one_nonvalid', 'one_valid_some_nonvalid', 'some_valid_some_nonvalid'])

            time_ns = get_sim_time(units='ns')
            if tnx_completed == 0:
                self.axis_if.tvalid.value = 1
            else:
                if(self.flow_ctrl ==  'one_valid_one_nonvalid'):                
                    if self.tvalid_state:
                        if tnx_completed:
                            self.tvalid_state = 0                            
                    else:
                        self.tvalid_state = 1
                    self.axis_if.tvalid.value = self.tvalid_state
                elif(self.flow_ctrl == 'one_valid_some_nonvalid'):
                    if self.tvalid_state:
                        tvalid_val = 1                        
                        self.tvalid_delay = random.randint(1,5)
                        self.tvalid_state = 0
                    else:
                        tvalid_val = 0
                        if self.tvalid_delay:
                            self.tvalid_delay -= 1
                        else:
                            self.tvalid_state = 1
                    self.axis_if.tvalid.value = tvalid_val
                elif(self.flow_ctrl == 'some_valid_some_nonvalid'):
                    if self.tvalid_delay:
                        self.tvalid_delay -= 1
                    else:
                        self.tvalid_delay = random.randint(1,5)
                        self.tvalid_state = self.tvalid_state ^ 1
                    self.axis_if.tvalid.value = self.tvalid_state
    
                else:
                    self.axis_if.tvalid.value = 1
        

    '''
    send_pkt() is a main corouting that controls the packet transmition
    '''
    
    async def send_pkt(self, pkt):
        self.tvalid_state = 1
        self.tvalid_delay = random.randint(1,5)
        tnx_completed = 0
        for x in range(pkt.delay):
            await RisingEdge(self.axis_if.aclk)
        word_num = 0
        pkt_len_in_words = math.ceil(pkt.pkt_size/self.width)
        while word_num < pkt_len_in_words:
            if(word_num == pkt_len_in_words-1):
                last_word = 1
            else:
                last_word = 0
                
            '''
            Send stimulus to DUT
            '''
            self.drive_tlast(last_word)
            self.drive_tuser(pkt, last_word)
            self.drive_tkeep(pkt, last_word)
            self.drive_tdata(pkt, last_word, word_num)
            self.drive_tvalid(tnx_completed)
            await RisingEdge(self.axis_if.aclk)
            tnx_completed = self.check_transaction_completion()
            if(tnx_completed):
                word_num += 1                
            
        if self.axis_if.tvalid is not None:
            self.axis_if.tvalid.value = 0
        if self.axis_if.tlast is not None:
            self.axis_if.tlast.value = 0
        #tvalid_state = 1

    '''
    send_interleaved_pkts() takes a list of packets and interleave it
    '''
    
    async def send_interleaved_pkts(self, pkts):
        self.tvalid_state = 1
        self.tvalid_delay = random.randint(1,5)
        self.current_index = 0
        pointers = [0] * len(pkts)
        packets_len = [math.ceil(len(x.data)/self.width) for x in pkts]
        tnx_completed = 0
        for x in range(pkts[0].delay):
            await RisingEdge(self.axis_if.aclk)
        while self.get_pkt_indx(packets_len, pointers, tnx_completed):
            if(pointers[self.current_index] == packets_len[self.current_index]-1):
                last_word = 1
            else:
                last_word = 0
            self.drive_tlast(last_word)
            self.drive_tuser(pkts[self.current_index], last_word)
            self.drive_tkeep(pkts[self.current_index], last_word)
            self.drive_tdata(pkts[self.current_index], last_word, pointers[self.current_index])
            self.drive_tvalid(tnx_completed)
            await RisingEdge(self.axis_if.aclk)
            tnx_completed = self.check_transaction_completion()
            if(tnx_completed):
                pointers[self.current_index] += 1
            
        if self.axis_if.tvalid is not None:
            self.axis_if.tvalid.value = 0
        if self.axis_if.tlast is not None:
            self.axis_if.tlast.value = 0

    '''
    Evaluates index of the packet that needs to be send in send_interleaved_pkts()
    '''
    
    def get_pkt_indx(self, pkts_len, pointers, tnx_completed):
        if tnx_completed:
            iter_cntr = 0
            while iter_cntr < len(pkts_len):
                self.current_index = (self.current_index + 1) % len(pkts_len)
                iter_cntr += 1
                if pointers[self.current_index] != pkts_len[self.current_index]:
                    return True
            return False
        else:
            return True

            #raise ValueError(f"All packets were transmitted.")
            
        
'''
AxisMonitor
'''

class AxisMonitor:
    def __init__(self, name, axis_if, aport=None, pkt0_word0=0, static_pkt=None):
        self.name      = name
        self.aport     = aport
        self.axis_if   = axis_if
        self.width     = axis_if.width        
        self.data      = []
        self.user      = []
        self.unpack    = axis_if.unpack
        self.pkt0_word0 = pkt0_word0
        self.static_pkt = static_pkt
        self.pkt_size = 0
        self.pkt_cntr = 0

    def mon_tuser(self):
        if self.axis_if.tuser is not None:
            if self.axis_if.tlast is not None:
                if self.axis_if.tlast.value == 1:
                    self.user.append(self.axis_if.tuser.value)
                    
    def mon_tkeep(self):
        if self.axis_if.tkeep is not None:
            if(self.axis_if.tkeep_type == 'packed'):
                tkeep_int_val = self.axis_if.tkeep.value
            elif(self.axis_if.tkeep_type == 'chisel_vec'):
                tkeep_int_val = 0
                for i in range(len(self.axis_if.tkeep)):
                    tkeep_int_val |= self.axis_if.tkeep[i].value << i                
            elif(self.axis_if.tkeep_type == 'ffs'):
                if(self.axis_if.tkeep.value == 0):
                    tkeep_int_val = 0
                else:
                    tkeep_int_val = (self.axis_if.tkeep.value << 1)-1
            tkeep_int = 0
            self.pkt_size += countones(tkeep_int_val)
            for byte_indx in range(0, self.width):
                if check_pos(tkeep_int_val, byte_indx):                    
                    tkeep_int |= 0xFF << (8 * byte_indx)
            tkeep_int = int(bin(tkeep_int)[:1:-1], 2)                        
        else:
            tkeep_int = (2 ** (8*self.width))-1
            self.pkt_size += self.width
        return tkeep_int
    
    async def mon_if(self):
        # Handle unpacked TDATA        
        
        while(True):
            await RisingEdge(self.axis_if.aclk)
            if(self.axis_if.tready is None):
                tnx_completed = self.axis_if.tvalid.value
            else:
                tnx_completed = self.axis_if.tvalid.value and self.axis_if.tready.value
            # TODO: Unify tdata_int
            if(tnx_completed):
                if(self.unpack == 'unpacked'):
                    tdata_int = 0
                    indx = 0
                    if(self.pkt0_word0):
                        byte_range = range(self.width)
                    else:
                        byte_range = range(self.width)[::-1]
                    # TODO: add non-byte word. Do we need it ?! 
                    for byte_indx in byte_range:
                        tdata_int = tdata_int | (self.axis_if.tdata.value[byte_indx] << indx*8)
                        indx += 1                        
                elif(self.unpack == 'packed'):                    
                    tdata_int = self.axis_if.tdata.value.integer
                    if(self.pkt0_word0 == 0):
                        tdata_rev = 0
                        if(self.width > 1):                            
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
                '''
                TUSER
                '''
                self.mon_tuser()
                
                #####################
                # Tkeep handle
                # 1. Filter valid bytes only
                # 2. Accumulate the packet size
                #####################                    
                # Append only valid data
                tkeep_int = self.mon_tkeep()
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
        pkt_mon.gen_user(self.user)
        # Clear data
        self.data = []
        self.user = []
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

    def __init__(self, name, axis_if, mode = 'ALWAYS_READY'):
        self.name = name
        self.axis_if = axis_if
        self.mode = mode

    async def tready_ctrl(self):
        if(self.mode == 'ALWAYS_READY'):
            self.axis_if.tready.value = 1
        elif(self.mode == 'BACKPRESSURE_1'):
            while True:
                self.axis_if.tready.value = 1
                while self.axis_if.tvalid.value == 0:
                    await RisingEdge(self.axis_if.aclk)
                await RisingEdge(self.axis_if.aclk)
                self.axis_if.tready.value = 1
                interval = random.randint(1,5)
                for cycle_num in range(interval):
                    await RisingEdge(self.axis_if.aclk)
                self.axis_if.tready.value = 0
                interval = random.randint(1,5)
                for cycle_num in range(0,interval):
                    await RisingEdge(self.axis_if.aclk)                        
        elif(self.mode == 'BACKPRESSURE_0'):
            while True:
                self.axis_if.tready.value = 0
                while self.axis_if.tvalid.value == 0:
                    await RisingEdge(self.axis_if.aclk)
                await RisingEdge(self.axis_if.aclk)
                interval = random.randint(1,5)
                for cycle_num in range(0,interval):
                    await RisingEdge(self.axis_if.aclk)                    
                self.axis_if.tready.value = 1
                await RisingEdge(self.axis_if.aclk)
                self.axis_if.tready.value = 0
                for cycle_num in range(0,5):
                    await RisingEdge(self.axis_if.aclk)
        else:
            assert False, "[ERROR] AxisResponder mode is not set."
                                
