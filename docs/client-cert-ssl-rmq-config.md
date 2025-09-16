
### openssl 

````commandline
touch ./cnf_0000000.cnf
nano ./cnf_0000000.cnf
````
````
[ req ]
default_bits = 2048
default_keyfile = key_0000000.pem
distinguished_name = req_distinguished_name
req_extensions = req_ext
prompt=no
[ req_distinguished_name ]
C=RU
ST=Moscow
L=Moscow
O=Leo4
OU=iot
CN=a3b0000000c99999d250813
emailAddress=0000000@leo4.ru
[ req_ext ]
subjectAltName = @alt_names
[alt_names]
DNS.1 = a3b0000000c99999d250813
DNS.2 = leo4-0000000.leo4.ru
DNS.3 = leo4-0000000.local
IP.1 = 192.168.1.100
IP.2 = 192.168.5.1
````
### Gen key & csr

````commandline
openssl req -out req_0000000.csr -newkey rsa:2048 -noenc -config cnf_0000000.cnf
````
#### Verify
````commandline
openssl req -text -noout -verify -in req_0000000.csr
````
#### Generate certificat
- CSR-file must be sent to CA
- cert_0000000.pem - must be received and saved

#### Docs openssl
- https://docs.openssl.org/master/man1/openssl-req/#examples

### Authentication with TLS/x509 client certificates
#### rabbit mqtt plugin config
````
ssl_cert_login_from = common_name
mqtt.ssl_cert_client_id_from = subject_alternative_name
# mqtt.ssl_cert_login_san_type = uri, dns, ip, email, other_name
````
##### Note that:

- The authenticated user must exist in the configured authentication / authorisation backend(s).
- Clients must not supply username and password.

##### config:
````
mqtt.allow_anonymous = false
anonymous_login_user = none

ssl_options.cacertfile = /path/to/ca_certificate.pem
ssl_options.certfile   = /path/to/server_certificate.pem
ssl_options.keyfile    = /path/to/server_key.pem
ssl_options.verify     = verify_peer
ssl_options.fail_if_no_peer_cert  = true

# default TLS-enabled port for MQTT connections
mqtt.listeners.ssl.default = 8883
mqtt.listeners.tcp.default = 1883
````
#### Note about users add to rabbit:
`PUT /api/users/{name}`

Creates a user. A password or a password hash must be provided in the payload:

`{"password":"secret","tags":"administrator"}`

`{"password_hash":"2lmoth8l4H0DViLaK9Fxi6l9ds8=", "tags":["administrator"]}`

* password_hash must be generated using the algorithm described in the Passwords guide.
* 
* The tags key takes a comma-separated list of tags.
* 
* If neither are set the user will not be able to log in with a password, but other mechanisms like client certificates may be used.
* 
* Setting password_hash to an empty string ("") will ensure the user cannot use a password to log in.

`PUT /api/topic-permissions/{vhost}/{user}`
Grants or updates a user's topic exchange permission of a user.

````json
{
  "exchange": "amq.topic",
  "write": "^a",
  "read":".*",
  "configure":".*"
}
````
_All the keys from the example above are mandatory._
