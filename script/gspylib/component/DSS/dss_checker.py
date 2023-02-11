# -*- coding:utf-8 -*-
#############################################################################
# Copyright (c) 2022 Huawei Technologies Co.,Ltd.
#
# openGauss is licensed under Mulan PSL v2.
# You can use this software according to the terms
# and conditions of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
#
#          http://license.coscl.org.cn/MulanPSL2
#
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS,
# WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the Mulan PSL v2 for more details.
# ----------------------------------------------------------------------------
# Description  : dss_checker.py is a utility to check parameter.

import os
import stat
import re
import sys
import base64
import json

try:
    sys.path.append(sys.path[0] + "/../../../")
    from gspylib.common.ErrorCode import ErrorCode
    from base_utils.security.security_checker import SecurityChecker
except ImportError as e:
    sys.exit("[GAUSS-52200] : Unable to import module: %s." % str(e))


class DssConfig():

    def __init__(self, attr='', unzip_str='', offset=0):
        self.ids = ''
        self.ips = ''
        self.ports = ''
        if attr:
            self.ids, self.ips, self.ports = attr
        self.offset = offset
        if unzip_str:
            infos = list(filter(None, re.split(r':|,', unzip_str.strip(','))))
            self.ids = infos[::3]
            self.ips = infos[1::3]
            self.ports = infos[2::3]

    @staticmethod
    def init_dss_config(inst):
        '''
        Initialize dssconfig based on the DN.
        '''
        if inst.enable_dss != 'on':
            return

        dn_inst = DssConfig.get_simple_value(inst, ['datanodes'])
        dss_ips = DssConfig.get_simple_value(dn_inst, ['haIps'])
        dss_ports = DssConfig.get_simple_value(dn_inst, ['port'])
        dss_ids = list(range(len(dss_ips)))
        inst.dss_config = str(
            DssConfig((dss_ids, dss_ips, dss_ports), offset=10))
        infos = list(filter(None, re.split(r':|,', inst.dss_vg_info)))
        if len(infos[::2]) != len(dss_ips) + 1:
            raise Exception(
                ErrorCode.GAUSS_500['GAUSS_50026'] % 'dss_vg_info' +
                ' The number of volumes is one more than the number of dns.' +
                ' The number of dns is {} and the number of dss volumes is {}'.
                format(len(dss_ips), len(infos[::2])))
        for dp in dss_ports:
            # The dms port is db port plus 10, and the dss port is db port plus 20.
            SecurityChecker.check_port_valid(
                'dataPortBase',
                int(dp),
                max_value=65535 - 20,
                des2='. In dss-mode, The DMS port number increases by 20 again')

    @staticmethod
    def get_simple_value(meta_object, award_key):
        '''
        type: award_key -> list
        No nesting logic is involved. Only key values are matched.
        '''

        res = []
        stack = [meta_object]
        while stack:
            sp = stack.pop(0)
            if isinstance(sp, list):
                for ele in sp:
                    stack.append(ele)
            elif isinstance(sp, dict):
                for key, value in sp.items():
                    if key in award_key:
                        if isinstance(value, list):
                            res.extend(value)
                        elif isinstance(value, int):
                            res.append(str(value))
                        else:
                            res.append(value)
                    else:
                        stack.append(value)
            elif hasattr(sp, '__dict__'):
                stack.append(vars(sp))
        return res

    @staticmethod
    def get_current_dss_id_by_dn(db_info, cur_db_info):
        '''
        Obtains the id of the current node's dssserver.
        '''

        dns = DssConfig.get_simple_value(db_info, ['datanodes'])
        cur_dns = DssConfig.get_simple_value(cur_db_info, ['datanodes'])
        if set(dns).intersection(set(cur_dns)):
            return dns.index(cur_dns[0])
        return -1

    @staticmethod
    def get_value_b64_handler(key, value, action='encode'):
        '''
        Quick use of base64
        '''
        if action == 'encode':
            b64_ans = base64.urlsafe_b64encode(
                json.dumps({
                    key: value
                }).encode()).decode()
        else:
            b64_ans = json.loads(
                base64.urlsafe_b64decode(value.encode()).decode()).get(
                    key, '')
        return b64_ans


    def __str__(self):
        '''
        return dss config str
        '''
        context = []
        for id_, ip, port in zip(self.ids, self.ips, self.ports):
            blocks = [str(id_), ip, str(int(port) + self.offset)]
            context.append(':'.join(blocks))
        return ','.join(context)


class DssSimpleChecker():

    def __init__(self):
        pass

    @staticmethod
    def check_vol_disk(device_name):
        """
        function: Check whether the device block exists.
        :param device_name:
        :return:
        """
        try:
            stat.S_ISBLK(os.stat(device_name).st_mode)
        except FileNotFoundError:
            raise Exception(ErrorCode.GAUSS_504["GAUSS_50421"] % device_name)

    @staticmethod
    def check_dss_vg_info(vgname, dss_vg_info):
        '''
        dss_vg_info checker
        '''
        infos = list(filter(None, re.split(r':|,', dss_vg_info)))

        # The volume name must correspond to the disk.
        if (dss_vg_info.count(':') != dss_vg_info.count(',') + 1) or (
                not infos) or (infos and len(infos) % 2 != 0):
            raise Exception(ErrorCode.GAUSS_504["GAUSS_50414"] %
                            "The volume name must correspond to the disk.")

        # The shared volume must be in vg_config.
        if vgname not in infos[::2]:
            raise Exception(ErrorCode.GAUSS_504["GAUSS_50419"] %
                            (vgname, dss_vg_info))

        for disk in infos[1::2]:
            DssSimpleChecker.check_vol_disk(disk)

    @staticmethod
    def check_dss_some_param(inst):
        '''
        Check some parameters on dss mode.
        '''
        names = [
            'dss_home', 'cm_vote_disk', 'cm_share_disk', 'dss_vgname',
            'dss_vg_info'
        ]
        for pn in names:
            if not getattr(inst, pn).strip():
                raise Exception(ErrorCode.GAUSS_500["GAUSS_50012"] % pn)

        DssSimpleChecker.check_vol_disk(inst.cm_vote_disk)
        DssSimpleChecker.check_vol_disk(inst.cm_share_disk)
        inst.dss_vg_info = inst.dss_vg_info.strip(',')

        # dss_vg_info checker
        DssSimpleChecker.check_dss_vg_info(inst.dss_vgname, inst.dss_vg_info)
        infos = list(filter(None, re.split(r':|,', inst.dss_vg_info)))
        all_disk = [inst.cm_vote_disk] + [inst.cm_share_disk] + infos[1::2]
        if len(all_disk) != len(set(all_disk)) or len(infos[::2]) != len(
                set(infos[::2])):
            raise Exception(ErrorCode.GAUSS_504["GAUSS_50417"])

        inst.dss_pri_disks = {
            k: v
            for k, v in zip(infos[::2], infos[1::2]) if k != inst.dss_vgname
        }
        inst.dss_shared_disks = {
            k: v
            for k, v in zip(infos[::2], infos[1::2]) if k == inst.dss_vgname
        }

        DssSimpleChecker.check_dss_ssl_enable(inst)
        DssSimpleChecker.check_rdma(inst)

    @staticmethod
    def check_dss_ssl_enable(inst):
        if inst.dss_ssl_enable.strip() in ['on', '']:
            inst.dss_ssl_enable = 'on'
        elif inst.dss_ssl_enable.strip() in ['off']:
            inst.dss_ssl_enable = 'off'
        else:
            raise Exception(ErrorCode.GAUSS_500['GAUSS_50026'] %
                            'dss_ssl_enable' + ' It\'s must be on or off')

    @staticmethod
    def check_rdma(inst):
        if inst.ss_interconnect_type in ['TCP', '']:
            pass
        elif inst.ss_interconnect_type in ['RDMA']:
            if inst.ss_rdma_work_config:
                mat = re.findall(r'(\d+) (\d+)', inst.ss_rdma_work_config)
                if mat:
                    first_cpu, lastest_cpu = mat[0]
                    if 0 <= int(first_cpu) <= int(lastest_cpu) < os.cpu_count():
                        return
                    raise Exception( ErrorCode.GAUSS_500["GAUSS_50027"] %
                        'ss_rdma_work_config' +
                        'The second number must be greater than the first number ' \
                             'and less than the number of CPU cores.'
                    )
                else:
                    raise Exception(
                        ErrorCode.GAUSS_500["GAUSS_50027"] %
                        'ss_rdma_work_config' +
                        'The format string is "int int"', )
        else:
            raise Exception(ErrorCode.GAUSS_500['GAUSS_50026'] %
                            'ss_interconnect_type' +
                            ' It\'s must be TCP or RDMA')