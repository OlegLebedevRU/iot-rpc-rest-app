import shutil
import subprocess
import datetime
from pathlib import Path
from random import randrange

node='s'
did = '0000'#'0000000'
command = 'D:/ESP32-ESP-IDF-tools/idf_cmd_init.bat esp-idf-94a3057652dd1832291ccc0b9c1c43d6'
cwd="D:/ESP32-ESP-IDF-tools/frameworks/esp-idf-v5.4"
ossl = 'D:/OpenSSL-Win64/bin/openssl'
capath = 'D:/ol-factory/ca'
fpath = 'd:/ol-factory'
ver=3

def gen_cert():
    snr = datetime.date.today().strftime("%d%m%y")
    snrnd = str(randrange(10001, 32765))
    sernum = 'a' + str(ver) + 'b' + did + 'c' + snrnd + 'd' + snr
    try:
       print(fpath+"/"+node+did)
       Path.mkdir((fpath+"/"+node+did))
       dpath = fpath+'/'+node+did
       shutil.copyfile(fpath + '/rootCA.crt', dpath + '/rootCA.crt')
       shutil.copyfile(fpath + '/gwCA.crt', dpath + '/gwCA.crt')
       shutil.copyfile(fpath + '/iot_leo4_ca.crt', dpath + '/iot_leo4_ca.crt')

       subprocess.run([ossl, 'genrsa','-out',dpath+'/key_'+did+'.pem','2048'])
       if node == 's':
           subj = '/C=RU/ST=Moscow/L=Moscow/CN=leo4-' + did +'.local' + '/O=Leo4/OU=IT/emailAddress=' + did + '@leo4.ru'
           ext = "subjectAltName = URI:" + sernum + ",DNS:leo4-" + did + ".local,IP:192.168.1.120"
           pass
       else:
           subj = '/C=RU/ST=Moscow/L=Moscow/CN='+sernum+'/O=Leo4/OU=IT/emailAddress='+did+'@leo4.ru'
           ext = "subjectAltName = URI:"+sernum+",DNS:leo4-"+did+".local"

       subprocess.run([ossl,'req','-new','-out',dpath+'/req_'+did+'.csr', '-key',dpath+'/key_'+did+'.pem' ,'-subj',subj, '-addext', ext])
       subprocess.run([ossl,'x509','-req','-in',dpath+'/req_'+did+'.csr',
                    '-CA',capath+'/ca.crt','-CAkey',capath+'/ca.key','-CAcreateserial','-copy_extensions=copyall',
                    '-out',dpath+'/cert_'+did+'.pem','-days','10950'])

    except:
        print("Fail create dir {}".format(fpath+'/'+'t'+did))

gen_cert()