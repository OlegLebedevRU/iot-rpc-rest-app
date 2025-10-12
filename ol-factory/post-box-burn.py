import csv
from pathlib import Path
import datetime
from random import randrange
import shutil
import subprocess

import requests

from fctry_part_data import factory_data
import time
#import cryptography
node = "t"
app_only=True
port='--port COM5'
did = '0004617'
hwversion = '3'
dev_type = 'y3-master' #usb
#dev_type = 'usb'
#dev_type = 'hongqi'
#dev_type = 't16'
cloud_mode = '0' # 0 - yandex, 1 - private
#device_version = '1' # 1 - Y1, 2 - Y2, 3 - Y3
ver=1
#command = 'D:/ESP32-ESP-IDF-tools/idf_cmd_init.bat esp-idf-94a3057652dd1832291ccc0b9c1c43d6'
command = '["powershell", "-Command", "C:\\Espressif\\tools\\Microsoft.v5.5.1.PowerShell_profile.ps1"]'
activate="C:\\Espressif\\tools\\Microsoft.v5.5.1.PowerShell_profile.ps1;"
#cwd="D:/ESP32-ESP-IDF-tools/frameworks/esp-idf-v5.4"
cwd="D:\\ESP32-ESP-IDF-tools\\.espressif\\v5.5.1\\esp-idf"
ossl = 'D:/OpenSSL-Win64/bin/openssl'
capath = 'D:/ol-factory/ca'
idf_path = 'D:\\ESP32-ESP-IDF-tools\\.espressif\\v5.5.1\\esp-idf'
partgen = idf_path+'/components/nvs_flash/nvs_partition_generator/nvs_partition_gen.py'
espsec = idf_path+'/components/esptool_py/esptool/espsecure.py'
esptool=idf_path+'/components/esptool_py/esptool/esptool.py'
espfuse=idf_path+'/components/esptool_py/esptool/espefuse.py'
fpath = 'd:/ol-factory'
bpath='D:/esp32-workplace-2025/post-box/build'
chip='--chip ESP32'
flash_mode='--flash_mode dio'

#----------------
snr = datetime.date.today().strftime("%d%m%y")
snrnd = str(randrange(10001, 32765))

pgen = subprocess.Popen(['powershell'], stdin=subprocess.PIPE)
if not (Path(fpath+'/'+'t'+did).exists()):
    sernum = 'a' + str(ver) + 'b' + did + 'c' + snrnd + 'd' + snr
    print(sernum)
    try:
       print(fpath+"/"+"t"+did)
       Path.mkdir((fpath+"/"+"t"+did))
       dpath = fpath+'/'+'t'+did
       shutil.copyfile(fpath + '/rootCA.crt', dpath + '/rootCA.crt')
       shutil.copyfile(fpath + '/gwCA.crt', dpath + '/gwCA.crt')
       shutil.copyfile(fpath + '/iot_leo4_ca.crt', dpath + '/iot_leo4_ca.crt')
       subprocess.run([ossl, 'genrsa','-out',dpath+'/key_'+did+'.pem','2048'])
       if node == 's':
           subj = '/C=RU/ST=Moscow/L=Moscow/CN=leo4-' + did +'.local' + '/O=Leo4/OU=IT/emailAddress=' + did + '@leo4.ru'
           ext = "subjectAltName = URI:" + sernum + ",DNS:leo4-" + did + ".local,IP:192.168.1.120"
           pass
       else:
           subj = '/C=RU/ST=Moscow/L=Moscow/CN='+sernum+'/O=0/OU='+did+'/emailAddress='+did+'@leo4.ru'
           ext = "subjectAltName = URI:"+sernum+",DNS:leo4-"+did+".local"

       subprocess.run([ossl,'req','-new','-out',dpath+'/req_'+did+'.csr', '-key',dpath+'/key_'+did+'.pem' ,'-subj',subj, '-addext', ext])
       subprocess.run([ossl,'x509','-req','-in',dpath+'/req_'+did+'.csr',
                    '-CA',capath+'/ca.crt','-CAkey',capath+'/ca.key','-CAcreateserial','-copy_extensions=copyall',
                    '-out',dpath+'/cert_'+did+'.pem','-days','10950'])
       #
       # subj = '/C=RU/ST=Moscow/L=Moscow/CN='+sernum+'/O=Leo4/OU=IT/emailAddress='+did+'@leo4.ru'
       # subprocess.run([ossl,'req','-new','-out',dpath+'/req_'+did+'.csr', '-key',dpath+'/key_'+did+'.pem' ,'-subj',subj])
       # subprocess.run([ossl,'x509','-req','-in',dpath+'/req_'+did+'.csr',
       #              '-CA',capath+'/ca.crt','-CAkey',capath+'/ca.key','-CAcreateserial',
       #              '-out',dpath+'/cert_'+did+'.pem','-days','10950'])
       # subprocess.run(["powershell", "C:\\Espressif\\tools\\Microsoft.v5.5.1.PowerShell_profile.ps1"
       #                 +' && '+'python '+ partgen+ ' generate-key '+ '--keyfile '+ 't' + did + '_nvs_key.bin '+ '--outdir '+ dpath]
       #                ,  shell=True,capture_output=True, text=True)

                                   #,activate,' python '+ partgen+ ' generate-key '+ '--keyfile '+ 't' + did + '_nvs_key.bin '+ '--outdir '+ dpath])
       pgen.communicate(input=(activate +('python '+ partgen+ ' generate-key '+ '--keyfile '+ 't' + did + '_nvs_key.bin '+ '--outdir '+ dpath)).encode())
       #pgen.wait()
       #pgen.communicate(input=('python '+ partgen+ ' generate-key '+ '--keyfile '+ 't' + did + '_nvs_key.bin '+ '--outdir '+ dpath).encode())
       pgen.wait()
    except:
        print("Fail create dir {}".format(fpath+'/'+'t'+did))
        #return 1
else:
    dpath = fpath + '/' + 't' + did
if app_only:
    print("app_only encrypt, merged... -> 9_app_only.cmd")
else:
    if dev_type == 'y3-single':
        board_type = '3'
        max_boards = '1'
        max_channels = '1'
    elif dev_type == 'y3-master':
        board_type = '3'
        max_boards = '3'
        max_channels = '16'
    elif dev_type == 'y2':
        board_type = '3'
        max_boards = '1'
        max_channels = '1'
    elif dev_type == 'hongqi':
        board_type = '1'
        max_boards = '10'
        max_channels = '25'
    else:
        board_type = '0'
        max_boards = '5'
        max_channels = '16'
    base_url = 'https://functions.yandexcloud.net/d4e44hdsr3rfvqdqhnoq?'
    reg_id = 'registryId=arenitkcek6vmnmj6ums'
    try:
        res = requests.get(base_url + reg_id + '&deviceName=t-' + did).json()
        if 'id' in res:
            if res['id'] == 'None':
                print("----- WARNING: new creating ycid")
                res1 = requests.get(
                    base_url + reg_id + '&deviceName=t-' + did + '&serialNumber=' + sernum + '&create=1').json()
                if 'id' in res1:
                    if res1['id'] == 'None':
                        print("----- FAIL: new creating ycid, None response")
                        ycid = '0'
                    else:
                        ycid = res1['id']
                else:
                    print("FAIL response create ycid")
                    ycid = '0'
            else:
                ycid = res['id']
        else:
            print("FAIL response get ycid")
            ycid = '0'
    except:
        print("Fail factory serverless function...")

    cmn1 = 'python ' + espsec + " generate_flash_encryption_key " + dpath + "/t" + did + "_flash_encryption_key.bin"
    with open(dpath + '/fctry_partition.csv', 'w', newline='') as factory_partition:
        writer = csv.writer(factory_partition, delimiter=',')
        data = factory_data(sernum,did,dpath, snr,board_type,max_boards,max_channels,hwversion,ycid)
        for d in data:
            writer.writerow(d)
# pfact = subprocess.Popen(['powershell',activate,' python '+ partgen+ ' encrypt '+ '--inputkey '+
#                     dpath + '/keys/t' + did + '_nvs_key.bin '+
#                     dpath + '/fctry_partition.csv '+ dpath + '/fctry_partition.bin '+ '0x10000'], shell=True, cwd=cwd)
pgen = subprocess.Popen(['powershell'], stdin=subprocess.PIPE)
pgen.communicate(input=(activate+'python '+ partgen+ ' encrypt '+ '--inputkey '+
                    dpath + '/keys/t' + did + '_nvs_key.bin '+
                    dpath + '/fctry_partition.csv '+ dpath + '/fctry_partition.bin '+ '0x10000').encode())
#pfact.wait()
pgen.wait()
pgen = subprocess.Popen(['powershell'], stdin=subprocess.PIPE)
pgen.communicate(input=(activate+'python '+ partgen+ ' generate '+
                    dpath + '/fctry_partition.csv '+ dpath + '/fctry_part_decr.bin '+ '0x10000').encode())
#pfact.wait()
pgen.wait()
# encrypt
if 'cmn1' in locals():
    print("create new flash_encryption keys")
else:
    print("use exist flash_encryption keys")
    cmn1='echo ...flash key exist...'


cmn2='python ' + espsec + ' encrypt_flash_data'+ ' --keyfile '+dpath+'/t'+did+'_flash_encryption_key.bin'+\
     ' --address'+' 0x1000'+' --output '+ dpath+'/bootloader-enc.bin '+bpath+'/bootloader/bootloader.bin'

cmn3='python ' + espsec +' encrypt_flash_data'+ ' --keyfile '+dpath+'/t'+did+'_flash_encryption_key.bin'+\
     ' --address'+' 0x10000'+' --output '+ dpath+'/partition-table-enc.bin '+bpath+'/partition_table/partition-table.bin'

cmn4='python ' + espsec +' encrypt_flash_data'+ ' --keyfile '+dpath+'/t'+did+'_flash_encryption_key.bin'+\
     ' --address'+' 0x100000'+' --output '+ dpath+'/app-enc.bin '+bpath+'/post-box.bin'

cmn5='python ' + espsec + ' encrypt_flash_data'+' --keyfile '+dpath+'/t'+did+'_flash_encryption_key.bin'+\
     ' --address'+' 0x15000'+' --output '+ dpath+'/otadata-enc.bin '+bpath+'/ota_data_initial.bin'

cmn6='python ' + espsec +' encrypt_flash_data'+ ' --keyfile '+dpath+'/t'+did+'_flash_encryption_key.bin'+\
     ' --address'+' 0x18000'+' --output '+ dpath+'/nvs-key-partition-enc.bin '+dpath+'/keys/t'+did+'_nvs_key.bin'

merge='python '+ esptool +' '+chip+  ' merge_bin -o ' +\
      dpath+'/merged-flash.bin '+flash_mode+ ' --flash_size 4MB' +\
      ' 0x1000 '+ dpath+'/bootloader-enc.bin' +\
      ' 0x10000 '+ dpath+'/partition-table-enc.bin' +\
      ' 0x100000 '+ dpath+'/app-enc.bin'+\
      ' 0x15000 '+ dpath+'/otadata-enc.bin' +\
      ' 0x18000 '+ dpath+'/nvs-key-partition-enc.bin' +\
      ' 0x19000 '+ dpath+'/fctry_partition.bin'
# not encrypted
merge_decr='python '+ esptool +' '+chip+  ' merge_bin -o ' +\
      dpath+'/merged-decr.bin '+flash_mode+ ' --flash_size 4MB' +\
      ' 0x1000 '+ bpath+'/bootloader/bootloader.bin' +\
      ' 0x10000 '+ bpath+'/partition_table/partition-table.bin' +\
      ' 0x100000 '+ bpath+'/post-box.bin'+\
      ' 0x15000 '+ bpath+'/ota_data_initial.bin' +\
      ' 0x19000 '+ dpath+'/fctry_part_decr.bin'
        #' 0x18000 '+ dpath+'/keys/t'+did+'_nvs_key.bin' +\
#pfkey = subprocess.Popen(['powershell',activate,' '+cmn1+'; ',cmn2+'; ',cmn3+'; ',cmn4+'; ',cmn5+'; ',cmn6+'; ',merge])
#,               shell=True, cwd=cwd, stdout = subprocess.DEVNULL
#pfkey.wait()
pfkey = subprocess.Popen(['powershell',activate,merge_decr])
#,               shell=True, cwd=cwd, stdout = subprocess.DEVNULL
pfkey.wait()
if app_only:
    with open(dpath + '/2_app_burn.cmd', 'w', newline='') as app_burn:
        app_burn.write(
            'python ' + esptool + ' ' + chip + ' --baud 460800 ' + port + ' write_flash --force 0x0 ' + dpath + '/merged-flash.bin\n')
else:
    with open(dpath + '/0_ya.cmd', 'w', newline='') as ya_cloud_cmd:
        ya_cloud_cmd.write(
            'yc iot device create --registry-name terminals --name t-' + did + ' >t-' + did + '-yc_iot_reg_detail.txt\n')
        ya_cloud_cmd.write('yc iot device certificate add --device-name t-' + did +
                           ' --certificate-file cert_' + did + '.pem >t-' + did + '-yc_iot_crt_detail.txt\n')
    with open(dpath + '/1_e_burn.cmd', 'w', newline='') as efuse_burn_1:
        efuse_burn_1.write(
            'python ' + esptool + ' ' + chip + ' --baud 115200 ' + port + ' --after no_reset erase_flash\n')
        efuse_burn_1.write('python ' + espfuse + ' --baud 115200 ' + port +
                           ' burn_key flash_encryption ' + dpath + '/t' +
                           did + '_flash_encryption_key.bin burn_key secure_boot_v2 D:/esp32-workplace/softAP/digest.bin '
                                 'burn_efuse FLASH_CRYPT_CNT 127 burn_efuse FLASH_CRYPT_CONFIG 0xF burn_efuse ABS_DONE_1\n')
    with open(dpath + '/2_app_burn.cmd', 'w', newline='') as app_burn:
        app_burn.write(
            'python ' + esptool + ' ' + chip + ' --baud 460800 ' + port + ' write_flash --force 0x0 ' + dpath + '/merged-flash.bin\n')
    with open(dpath + '/2_decr_app_burn.cmd', 'w', newline='') as app_burn:
        app_burn.write(
            'python ' + esptool + ' ' + chip + ' --baud 460800 ' + port + ' write_flash --force 0x0 ' + dpath + '/merged-decr.bin\n')

    with open(dpath + '/3_e_burn.cmd', 'w', newline='') as efuse_burn_3:
        efuse_burn_3.write('python ' + espfuse + ' --baud 115200 ' + port +
                           ' burn_efuse DISABLE_DL_ENCRYPT 0x1 burn_efuse DISABLE_DL_DECRYPT 0x1 '
                           'burn_efuse DISABLE_DL_CACHE 0x1 burn_efuse JTAG_DISABLE 0x1 write_protect_efuse MAC '
                           'write_protect_efuse RD_DIS write_protect_efuse DISABLE_DL_ENCRYPT\n')

#echo yc iot device create --registry-name terminals --name t-%1 >t-%1-yc_iot_reg_detail.txt >.\t%1\yc_reg.cmd

#echo yc iot device certificate add --device-name t-%1 --certificate-file cert_%1.pem >t-%1-yc_iot_crt_detail.txt >>.\t%1\yc_reg.cmd