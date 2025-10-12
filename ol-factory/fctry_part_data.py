

def factory_data (
        sernum,
        did,
        dpath,
        snr,
        board_type,
        max_boards,
        max_channels,
        hwversion,
        ycid
    ):
    leo4 = []
    leo4.append(['key', 'type', 'encoding', 'value'])
    leo4.append(['ids', 'namespace', '', ''])
    leo4.append(['device_int_id', 'data', 'i32', did])
    leo4.append(['device_id', 'data', 'string', ycid])
    leo4.append(['registries_id', 'data', 'string', 'arenitkcek6vmnmj6ums'])
    leo4.append(['serial_no', 'data', 'string', sernum])

    leo4.append(['olcon_ns', 'namespace', '', ''])
    leo4.append(['device_id', 'data', 'string', ycid])
    leo4.append(['registries_id', 'data', 'string', 'arenitkcek6vmnmj6ums'])
    leo4.append(['topic_sub', 'data', 'string', '$me/device/commands/olconapi'])
    leo4.append(['topic_pub', 'data', 'string', '$registries/arenitkcek6vmnmj6ums/events/olconapi'])
    leo4.append(['topic_mon', 'data', 'string', '$me/monitoring/json'])
    leo4.append(['topic_upd', 'data', 'string', '$me/device/commands/update'])

    leo4.append(['topic_events', 'data', 'string', sernum + '/events'])
    leo4.append(['topic_rpl', 'data', 'string', sernum + '/rpl'])
    leo4.append(['topic_hch', 'data', 'string', sernum + '/hch'])
    leo4.append(['topic_commands', 'data', 'string', sernum + '/commands'])
    leo4.append(['topic_update', 'data', 'string', sernum + '/update'])

    leo4.append(['mqtt_uri', 'data', 'string', 'mqtts://mqtt.cloud.yandex.net:8883'])
    leo4.append(['broker_url', 'data', 'string', 'mqtts://iot.leo4.ru:8883'])
    leo4.append(['base_leo4_url', 'data', 'string', 'iot.leo4.ru'])
    leo4.append(['qr_base_url', 'data', 'string', 'https://d5dtmk5dd91f4oib0oup.apigw.yandexcloud.net'])
    leo4.append(['phone_number', 'data', 'string', '+7-916-000-0000'])
    leo4.append(['eth_ip', 'data', 'string', '192.168.1.101'])
    leo4.append(['eth_netmask', 'data', 'string', '255.255.255.0'])
    leo4.append(['eth_gw', 'data', 'string', '192.168.1.1'])
    leo4.append(['wf_sta_ssid', 'data', 'string', 'leo4'])
    leo4.append(['wf_sta_password', 'data', 'string', 'leo41234'])
    leo4.append(['wf_ap_ip', 'data', 'string', '192.168.5.1'])
    leo4.append(['wf_ap_netmask', 'data', 'string', '255.255.255.0'])
    leo4.append(['wf_ap_password', 'data', 'string', 'leo41234'])
    leo4.append(['ntp_server_url', 'data', 'string', 'pool.ntp.org'])
    leo4.append(['api_url_pref', 'data', 'string', 'd5dbnvm0kd5ames2tb0o'])
    leo4.append(['wf_ap_ssid', 'data', 'string', 'leo4_' + did])
    leo4.append(['device_int_id', 'data', 'i32', did])
    leo4.append(['serial_no', 'data', 'string', sernum])
    leo4.append(['qr_pattern', 'data', 'u8', '0'])
    leo4.append(['sensor_lock', 'data', 'u8', '1'])
    leo4.append(['board_type', 'data', 'u8', board_type])
    leo4.append(['max_boards', 'data', 'u8', max_boards])
    leo4.append(['max_channels', 'data', 'u8', max_channels])
    leo4.append(['init_page_num', 'data', 'u8', '0'])
    leo4.append(['pulse_duration', 'data', 'u8', '2'])
    leo4.append(['eth_ip_mode', 'data', 'u8', '0'])
    leo4.append(['wf_mode', 'data', 'u8', '1'])
    leo4.append(['mqtt_mode', 'data', 'u8', '1'])
    # leo4.append(['device_version', 'data', 'u8', device_version])
    leo4.append(['baudrate0', 'data', 'i32', '115200'])
    leo4.append(['baudrate1', 'data', 'i32', '115200'])
    leo4.append(['baudrate2', 'data', 'i32', '115200'])
    leo4.append(['databits0', 'data', 'u8', '8'])
    leo4.append(['databits1', 'data', 'u8', '8'])
    leo4.append(['databits2', 'data', 'u8', '8'])
    leo4.append(['parity0', 'data', 'u8', '0'])
    leo4.append(['parity1', 'data', 'u8', '0'])
    leo4.append(['parity2', 'data', 'u8', '0'])
    leo4.append(['stopbits0', 'data', 'u8', '1'])
    leo4.append(['stopbits1', 'data', 'u8', '1'])
    leo4.append(['stopbits2', 'data', 'u8', '1'])
    leo4.append(['uart0_to_mqtt', 'data', 'u8', '0'])
    leo4.append(['uart1_to_mqtt', 'data', 'u8', '0'])
    leo4.append(['uart2_to_mqtt', 'data', 'u8', '0'])
    leo4.append(['uart2_de_ctrl', 'data', 'u8', '1'])
    leo4.append(['app_cfg_id', 'data', 'u8', '2'])
    leo4.append(['ui_cfg_id', 'data', 'u8', '0'])
    leo4.append(['uart0_config', 'data', 'u8', '0'])
    leo4.append(['sleep_mode', 'data', 'u8', '0'])
    leo4.append(['wake_button', 'data', 'u8', '0'])
    leo4.append(['sleep_trigger', 'data', 'u8', '0'])
    leo4.append(['wake_timer', 'data', 'i32', '600'])
    leo4.append(['sleep_tr_time', 'data', 'i32', '60'])
    leo4.append(['ws_mode', 'data', 'u8', '1'])
    leo4.append(['ws_password', 'data', 'string', 'leo41234'])
    leo4.append(['web_shtdwn_time', 'data', 'i32', '15'])
    leo4.append(['hw_version', 'data', 'u8', hwversion])
    # duplicate deprecated
    leo4.append(['ca_cert', 'file', 'binary', dpath + '/rootCA.crt'])
    leo4.append(['scrt_fname', 'data', 'string', 'rootCA.crt'])
    leo4.append(['scrt_ftime', 'data', 'string', snr])
    leo4.append(['scrt_fsize', 'data', 'i32', '4096'])
    leo4.append(['cert', 'file', 'binary', dpath + '/cert_' + did + '.pem'])
    leo4.append(['ccrt_fname', 'data', 'string', 'cert_' + did + '.pem'])
    leo4.append(['ccrt_ftime', 'data', 'string', snr])
    leo4.append(['ccrt_fsize', 'data', 'i32', '4096'])
    leo4.append(['priv_key', 'file', 'binary', dpath + '/key_' + did + '.pem'])
    leo4.append(['ckey_fname', 'data', 'string', 'key_' + did + '.pem'])
    leo4.append(['ckey_ftime', 'data', 'string', snr])
    leo4.append(['ckey_fsize', 'data', 'i32', '4096'])
    leo4.append(['iot_leo4_ca', 'file', 'binary', dpath + '/iot_leo4_ca.crt'])
    leo4.append(['iot_leo4_local', 'file', 'binary', dpath + '/iotleo4local.crt'])
    #leo4.append(['ota', 'namespace', '', ''])
    leo4.append(['gw_cert', 'file', 'binary', dpath + '/gwCA.crt'])
    leo4.append(['iot_leo4_ca', 'file', 'binary', dpath + '/iot_leo4_ca.crt'])
    leo4.append(['iot_leo4_local', 'file', 'binary', dpath + '/iotleo4local.crt'])
    return leo4

def certs_data (

        did,
        dpath,
        snr
    ):
    leo4 = []
    leo4.append(['key', 'type', 'encoding', 'value'])
    leo4.append(['mqtt', 'namespace', '', ''])
    leo4.append(['ca_cert', 'file', 'binary', dpath + '/rootCA.crt'])
    leo4.append(['scrt_fname', 'data', 'string', 'rootCA.crt'])
    leo4.append(['scrt_ftime', 'data', 'string', snr])
    leo4.append(['scrt_fsize', 'data', 'i32', '4096'])
    leo4.append(['cert', 'file', 'binary', dpath + '/cert_' + did + '.pem'])
    leo4.append(['ccrt_fname', 'data', 'string', 'cert_' + did + '.pem'])
    leo4.append(['ccrt_ftime', 'data', 'string', snr])
    leo4.append(['ccrt_fsize', 'data', 'i32', '4096'])
    leo4.append(['priv_key', 'file', 'binary', dpath + '/key_' + did + '.pem'])
    leo4.append(['ckey_fname', 'data', 'string', 'key_' + did + '.pem'])
    leo4.append(['ckey_ftime', 'data', 'string', snr])
    leo4.append(['ckey_fsize', 'data', 'i32', '4096'])
    leo4.append(['iot_leo4_ca', 'file', 'binary', dpath + '/iot_leo4_ca.crt'])
    leo4.append(['iot_leo4_local', 'file', 'binary', dpath + '/iotleo4local.crt'])
    leo4.append(['ota', 'namespace', '', ''])
    leo4.append(['gw_cert', 'file', 'binary', dpath + '/gwCA.crt'])
    leo4.append(['iot_leo4_ca', 'file', 'binary', dpath + '/iot_leo4_ca.crt'])
    leo4.append(['iot_leo4_local', 'file', 'binary', dpath + '/iotleo4local.crt'])

    return leo4