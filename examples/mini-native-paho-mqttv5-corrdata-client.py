import json
import os
import ssl
import uuid
from time import sleep
from pydantic import BaseModel, JsonValue
import paho.mqtt.client as mqtt
from paho.mqtt.packettypes import PacketTypes
from pydantic import UUID4
import json
import sys
from OpenSSL import crypto

class DevTaskLoaded(BaseModel):
    id: UUID4
    method_code: int
    device_id : int
    payload: JsonValue



def on_message(client, userdata, msg):
    print("topic = " + msg.topic)
    # UserProperty : [('method_code', '0077')]
    if hasattr(msg.properties, 'CorrelationData'):
        print("Native msg.properties.CorrelationData = " +  str(msg.properties.CorrelationData.decode()))
    print(str(msg.payload))
    print(str(msg.properties))
    if hasattr(json.loads(msg.payload.decode()),'payload'):
        print("payload = " + str(json.loads(msg.payload.decode())['payload']))
    if msg.topic.endswith("tsk"):
        props = mqtt.Properties(PacketTypes.PUBLISH)
        if hasattr(msg.properties, 'CorrelationData'):
            props.CorrelationData = msg.properties.CorrelationData #.bytes
            mqttc.publish("dev/"+cert["CN"]+"/req",
                          f"from device req, corr data = {str(msg.properties.CorrelationData.decode())}",
                          qos=0,
                          properties=props)
            print(f"req = {msg.topic[:-3]}")
        else:
            return
    elif msg.topic.endswith("rsp"):
        props = mqtt.Properties(PacketTypes.PUBLISH)
        #props2 = mqtt.Properties(PacketTypes.PUBLISH)
        if hasattr(msg.properties, 'CorrelationData'):
            props.CorrelationData = msg.properties.CorrelationData #.bytes
            props.UserProperty = [("status_code", "206"), ("ext_id", "12345")]
            mqttc.publish("dev/"+cert["CN"]+"/res",
                          json.dumps({"description":"from device partial result", "corr_data": f"{str(msg.properties.CorrelationData.decode())}"}),
                          qos=0,
                          properties=props)
            #props2.CorrelationData = msg.properties.CorrelationData
            props.clear()
            props.CorrelationData = msg.properties.CorrelationData
            props.UserProperty = [("status_code", "200"), ("ext_id", "12345")]
            mqttc.publish("dev/"+cert["CN"]+"/res",
                          json.dumps({"description":"from device final result", "corr_data": f"{str(msg.properties.CorrelationData.decode())}"}),
                          qos=0,
                          properties=props)
            print(str(props))
            #print(f"RESPONSE = {msg.topic[:-3]}")
        else:
            return

# mqtt
def on_connect(client, userdata, flags, reason_code, properties):
    #pass
    #client.subscribe("$SYS/broker/log/#", qos=1)
    #client.subscribe("device/+/resp", qos=1)
    print(reason_code)
    print(userdata)
    print(flags)
    print(properties)
    client.subscribe("srv/"+cert["CN"]+"/tsk", qos=0)
    client.subscribe("srv/"+cert["CN"]+"/rsp", qos=0)

os.environ["PATH"] += os.pathsep + "D:/OpenSSL-Win64/bin/"
with open("D:/ol-factory/t0000000/cert_0000000.pem", 'rb') as pem_file: #sys.argv[1], 'rb'
    x509 = crypto.load_certificate(crypto.FILETYPE_PEM, pem_file.read())

# json.dump({name.decode(): value.decode('utf-8')
#            for name, value in x509.get_subject().get_components()},
#           sys.stdout, indent=2, ensure_ascii=False)
cert = ({name.decode(): value.decode('utf-8')
           for name, value in x509.get_subject().get_components()})
print(cert["CN"])
mqttc = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv5, client_id=cert["CN"]) #"a3b0000000c10221d290825")
#mqttc.username_pw_set('user', 'root')
mqttc.on_message = on_message
mqttc.on_connect = on_connect
mqttc.tls_set("D:/work/iot.leo4.ru/iot_leo4_ca.crt",
              "D:/ol-factory/t0000000/cert_0000000.pem",
              "D:/ol-factory/t0000000/key_0000000.pem",
              tls_version=ssl.PROTOCOL_TLSv1_2)
#mqttc.connect(host="192.168.1.120", port=8883)
mqttc.connect(host="dev.leo4.ru", port=8883)
mqttc.loop_start()
i=0
while True:

    #sleep(90)
    i=i+1
    props = mqtt.Properties(PacketTypes.PUBLISH)
    props.CorrelationData = uuid.UUID(int=0).bytes #uuid.uuid4().bytes
    #props.ResponseTopic = "srv/"+cert["CN"]+"/rsp"
    props.UserProperty=[("event_type_code","90"),("dev_event_id",f"{10000+i}")]
    mqttc.publish("dev/"+cert["CN"]+"/evt", "{\"test\":"+f"\"event = {i}"+"\"}",
                  qos=0,
                  properties=props)
    #mqttc.publish("dev/" + cert["CN"] + "/req", f"req = {i}",
    #             qos=0, properties=props
    #             )
    print(f"device side, prepare send to request topic, test iteration = {i}")
    #mqttc.disconnect()
    sleep(60)


#mqttc.loop_forever()
