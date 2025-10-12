'''
https://www.misterpki.com/pkcs7/
https://cryptography.io/en/latest/hazmat/primitives/asymmetric/serialization/#pkcs7
https://github.com/pyca/cryptography/blob/main/tests/hazmat/primitives/test_pkcs7.py#L1428
'''

import datetime
import os
from ipaddress import IPv4Address

#import OpenSSL
from OpenSSL import crypto
from cryptography import x509
from cryptography.hazmat._oid import ExtensionOID
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from cryptography.x509 import load_pem_x509_csr, DNSName, IPAddress

os.environ["PATH"] += os.pathsep + "D:/OpenSSL-Win64/bin/"

with open("D:/ol-factory/ca/ca.crt", 'rb') as pem_file: #sys.argv[1], 'rb'
    #x509v = crypto.load_certificate(crypto.FILETYPE_PEM, pem_file.read())
    ca_crt = x509.load_pem_x509_certificate(pem_file.read())

# json.dump({name.decode(): value.decode('utf-8')
#            for name, value in x509.get_subject().get_components()},
#           sys.stdout, indent=2, ensure_ascii=False)
# cert = ({name.decode(): value.decode('utf-8')
#            for name, value in x509v.get_subject().get_components()})
# ca_subj = x509v.get_subject()
#print(cert["CN"])

# ca_subject = x509.Name([
#         x509.NameAttribute(x509.NameOID.COMMON_NAME, cert["CN"]),
#         x509.NameAttribute(x509.NameOID.ORGANIZATION_NAME, cert["O"]),
#         x509.NameAttribute(x509.NameOID.ORGANIZATIONAL_UNIT_NAME, cert["OU"]),
#         x509.NameAttribute(x509.NameOID.LOCALITY_NAME, cert["L"]),
#         x509.NameAttribute(x509.NameOID.COUNTRY_NAME, cert["C"]),
#         x509.NameAttribute(x509.NameOID.STATE_OR_PROVINCE_NAME, cert["ST"]),
#         x509.NameAttribute(x509.NameOID.EMAIL_ADDRESS, cert["emailAddress"]),
#     ])
# def generate_ca():
#     # Create a new RSA key pair for the CA
#     ca_key = rsa.generate_private_key(
#         public_exponent=65537,
#         key_size=2048,
#         backend=default_backend()
#     )

    # Create a new subject for the CA


    # Create a new certificate for the CA
    # ca_cert = (
    #     x509.CertificateBuilder()
    #     .subject_name(ca_subject)
    #     .issuer_name(ca_subject)
    #     .public_key(ca_key.public_key())
    #     .serial_number(x509.random_serial_number())
    #     .not_valid_before(datetime.datetime.now())
    #     .not_valid_after(datetime.datetime.now() + datetime.timedelta(days=365))
    #     .add_extension(
    #         x509.BasicConstraints(
    #             ca=True, path_length=None
    #         ),
    #         critical=True
    #     )
    #     .sign(
    #         ca_key,
    #         hashes.SHA256(),
    #         default_backend()
    #     )
    # )
    #
    # return ca_key, ca_cert

def generate_server_cert(common_name, organization_name, organization_unit, address, country_name, ca_key, csr_in):
    # Create a new RSA key pair for the server
    server_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend()
    )

    # Create a new subject for the server
    server_subject = x509.Name([
        x509.NameAttribute(x509.NameOID.COMMON_NAME, u"{}".format(common_name)),
        x509.NameAttribute(x509.NameOID.ORGANIZATION_NAME, u"{}".format(organization_name)),
        x509.NameAttribute(x509.NameOID.ORGANIZATIONAL_UNIT_NAME, u"{}".format(organization_unit)),
        x509.NameAttribute(x509.NameOID.STREET_ADDRESS, u"{}".format(address)),
        x509.NameAttribute(x509.NameOID.COUNTRY_NAME, u"{}".format(country_name)),
    ])

    # create csr if stand alone
    # # Generate a CSR
    csr = (x509.CertificateSigningRequestBuilder().subject_name(server_subject)
           .add_extension(
        x509.SubjectAlternativeName([x509.DNSName(common_name),
                                     x509.UniformResourceIdentifier(common_name)]),  # a3b0000000c10221d290825
        critical=False)
           .sign(server_key, hashes.SHA256(),default_backend())) # Sign the CSR with the private key.


    #Here is the code to create a certificate from a CSR signed by a CA:
# CA sign csr
# def sign_certificate_request(csr_cert, ca_cert, private_ca_key):
    ext = csr_in.extensions.get_extension_for_class(x509.SubjectAlternativeName)
    ext1 = x509.SubjectAlternativeName([x509.IPAddress(IPv4Address("192.168.1.120")),
                                        x509.DNSName(ext.value.get_values_for_type(DNSName)[0]),
                                        x509.IPAddress(IPv4Address(ext.value.get_values_for_type(IPAddress)[0])
                                                       if len(ext.value.get_values_for_type(IPAddress))>0 else
                                                       IPv4Address("192.168.1.100"))
                                        ])
    ext3= x509.SubjectAlternativeName(x509.GeneralNames(ext.value)).get_values_for_type(DNSName)
    ext2 = x509.SubjectAlternativeName(x509.GeneralNames(ext.value))
    for val in ext.value: print(val)
    print(ext3)
    print((ext1.get_values_for_type(IPAddress)))
    print(ext1)
    # server_cert = (x509.CertificateBuilder().subject_name(csr_in.subject)
    #         .issuer_name(ca_subject  ) #ca_cert.subject
    #         .public_key(csr_in.public_key())
    #         .serial_number(x509.random_serial_number())
    #         .not_valid_before(datetime.datetime.now())  # Our certificate will be valid for 10 days
    #         .not_valid_after(datetime.datetime.now() + datetime.timedelta(days=10)) # Sign our certificate with our private key
    #         .add_extension(ext1, critical=False)
    #         #.add_extension(ext.value, ext.critical ) #Extensions from csr
    #         #.add_extension(x509.SubjectAlternativeName([x509.IPAddress(IPv4Address("192.168.1.120")),]),critical=False)
    #         .sign(ca_key, hashes.SHA256(),default_backend()))
#
#     # return DER certificate
#     return cert.public_bytes(serialization.Encoding.DER)
# csr_cert is the cryptography CSR certificate object - can be loaded from a file with x509.load_der_x509_csr()
# ca_cert is the cryptography certificate object - can be loaded from a file with x509.load_pem_x509_certificate()
# private_ca_key is the cryptography private key object - can be loaded from a file with serialization.load_pem_private_key()

    #Create a new certificate for the server
    # 176.108.247.249
    # 84.252.138.131
    # iot.leo4.ru
    # dev.leo4.ru
    # api.leo4.ru
    server_cert = (
        x509.CertificateBuilder()
        .subject_name(server_subject)
        #.issuer_name(x509v.Name)

        .issuer_name(ca_crt.issuer)
        .public_key(server_key.public_key()) #get from private key instead get from signed csr
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.now()-datetime.timedelta(days=1))
        .not_valid_after(datetime.datetime.now() + datetime.timedelta(days=365))
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()),


            critical=False
        ).add_extension(
            x509.SubjectAlternativeName([x509.DNSName(common_name),x509.DNSName("iot.leo4.ru"),x509.DNSName("api.leo4.ru"),
                                         x509.IPAddress(IPv4Address("176.108.247.249")),x509.IPAddress(IPv4Address("84.252.138.131")),
                                         x509.UniformResourceIdentifier(common_name)]),
            critical=False
        )
        .sign(
            ca_key,
            hashes.SHA256(),
            default_backend()
        )
    )

    return server_key, server_cert

# Generate a CA key pair and certificate
#ca_key, ca_cert = generate_ca()
with open("D:/ol-factory/ca/ca.key", 'rb') as pem_file: #sys.argv[1], 'rb'
    #x509 = crypto.load_privatekey(crypto.FILETYPE_PEM,pem_file.read())  #.load_certificate(crypto.FILETYPE_PEM, pem_file.read())
    ca_key = load_pem_private_key(pem_file.read(), None, unsafe_skip_rsa_key_validation=False)
# Generate a server certificate and private key
with open("D:/ol-factory/t0000000/req_0000000.csr", 'rb') as pem_file: #sys.argv[1], 'rb'
    #x509 = crypto.load_privatekey(crypto.FILETYPE_PEM,pem_file.read())  #.load_certificate(crypto.FILETYPE_PEM, pem_file.read())
    csr_in = load_pem_x509_csr(pem_file.read(), None)
server_key, server_cert = generate_server_cert(
    "dev.leo4.ru",
    #"a3b0000000c10221d290825",
    "Leo4",
    "Dev",
    "Moscow",
    "RU",
    ca_key,
    csr_in

)

# Save the CA certificate to a file
# with open("ca.crt", "wb") as f:
#     f.write(ca_cert.public_bytes(serialization.Encoding.PEM))

# Save the server certificate to a file
with open("dev_leo4.crt", "wb") as f:
    f.write(server_cert.public_bytes(serialization.Encoding.PEM))

# Save the server private key to a file
with open("dev_leo4.key", "wb") as f:
    f.write(server_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    ))
jwt_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=1024,
        backend=default_backend()
    )
claim = {'test': "hello"}

import jwt
token = jwt.encode(
    claim,
    jwt_key,
    algorithm='RS256')
print(token)