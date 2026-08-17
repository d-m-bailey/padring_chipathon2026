ROOT_DIR=$(abspath ../)
include $(ROOT_DIR)/settings.mk
PADRING_DIR=$(abspath .)
SIGN_DIR=$(abspath ../signoff)

PDK_ROOT?=/foss/pdks
PDK?=PDK?=gf180mcuD
TECH_PDK=$(PDK_ROOT)/$(PDK)
PDK_FILE?=none
PDK_KFILE ?= $(TECH_PDK)/libs.tech/klayout/tech/gf180mcu.lyp

DEF=$(PADRING_DIR)/outputs/workshop_padring.def
GDS=$(PADRING_DIR)/outputs/workshop_padring.gds
BIN_DIR=$(HOME)/chipathon/2026/padring/build

export SIGN_DIR
export ROOT_DIR

all: $(DEF)

$(DEF): $(SYN_NET) $(PADRING_DIR)/workshop_padring.cfg
	mkdir -p $(PADRING_DIR)/outputs
	$(BIN_DIR)/padring -v --lef $(TECH_PDK)/libs.ref/gf180mcu_fd_io/lef/gf180mcu_fd_io__cor.lef --lef $(TECH_PDK)/libs.ref/gf180mcu_fd_io/lef/gf180mcu_fd_io__fill1.lef --lef $(TECH_PDK)/libs.ref/gf180mcu_fd_io/lef/gf180mcu_fd_io__bi_t.lef --lef $(TECH_PDK)/libs.ref/gf180mcu_fd_io/lef/gf180mcu_fd_io__asig_5p0.lef --lef $(TECH_PDK)/libs.ref/gf180mcu_fd_io/lef/gf180mcu_fd_io__dvdd.lef --lef $(TECH_PDK)/libs.ref/gf180mcu_fd_io/lef/gf180mcu_fd_io__dvss.lef --svg $(PADRING_DIR)/outputs/workshop_padring.svg --def $(DEF) $(PADRING_DIR)/workshop_padring.cfg | tee $(PADRING_DIR)/workshop_padring.log
	#--ver $(PADRING_DIR)/outputs/workshop_padring.v --csv $(PADRING_DIR)/outputs/workshop_padring.csv 

gds: $(GDS)

$(GDS): $(ROOT_DIR)/def2stream.py $(DEF)
	mkdir -p $(SIGN_DIR)/outputs
	mkdir -p $(SIGN_DIR)/reports
ifeq ($(PDK_FILE),none)
	klayout -zz -rd design_name=workshop_padring \
	        -rd in_def=$(DEF) \
	        -rd lef_files="$(ROOT_DIR)/lib/$(TECH).tech.lef $(ROOT_DIR)/lib/$(TECH).lef $(TECH_PDK)/libs.ref/gf180mcu_fd_io/lef/gf180mcu_fd_io__cor.lef $(TECH_PDK)/libs.ref/gf180mcu_fd_io/lef/gf180mcu_fd_io__fill1.lef $(TECH_PDK)/libs.ref/gf180mcu_fd_io/lef/gf180mcu_fd_io__bi_t.lef $(TECH_PDK)/libs.ref/gf180mcu_fd_io/lef/gf180mcu_fd_io__asig_5p0.lef $(TECH_PDK)/libs.ref/gf180mcu_fd_io/lef/gf180mcu_fd_io__dvdd.lef $(TECH_PDK)/libs.ref/gf180mcu_fd_io/lef/gf180mcu_fd_io__dvss.lef" \
	        -rd in_files="$(TECH_PDK)/libs.ref/gf180mcu_fd_io/gds/gf180mcu_fd_io.gds " \
	        -rd seal_file="" \
	        -rd out_file=$(GDS) \
	        -rd tech_file=$(TECH_PDK)/libs.tech/klayout/tech/gf180mcu.lyt \
	        -rd layer_map=$(TECH_PDK)/libs.tech/klayout/tech/gf180mcu.map \
	        -r $(ROOT_DIR)/def2stream.py
else
	magic -dnull -noconsole -rcfile $(PDK_ROOT)/$(PDK)/libs.tech/magic/$(PDK).magicrc $(SIGN_DIR)/tcl/gds.tcl
endif

view: $(GDS)
	klayout -s $(GDS) -l $(PDK_KFILE)

clean:
	rm -vrf fv/ outputs reports *.size *.log DesignLib

.PHONY: all manual clean

