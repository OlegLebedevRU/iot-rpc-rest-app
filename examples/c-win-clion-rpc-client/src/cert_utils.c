/**
 * @file cert_utils.c
 * @brief Извлечение CN из X.509 PEM-сертификата через OpenSSL.
 */

#include "cert_utils.h"

#include <stdio.h>
#include <string.h>

#include <openssl/pem.h>
#include <openssl/x509.h>

int extract_cn_from_cert(const char *cert_path, char *cn_buf, size_t cn_buf_len)
{
    FILE *fp = NULL;
    X509 *cert = NULL;
    X509_NAME *subject = NULL;
    int idx;
    int rc = -1;

    if (!cert_path || !cn_buf || cn_buf_len == 0) {
        fprintf(stderr, "[CERT] Invalid parameters\n");
        return -1;
    }

#ifdef _WIN32
    if (fopen_s(&fp, cert_path, "r") != 0 || !fp) {
#else
    fp = fopen(cert_path, "r");
    if (!fp) {
#endif
        fprintf(stderr, "[CERT] Failed to open file: %s\n", cert_path);
        return -1;
    }

    cert = PEM_read_X509(fp, NULL, NULL, NULL);
    fclose(fp);

    if (!cert) {
        fprintf(stderr, "[CERT] Failed to read X.509 certificate from: %s\n",
                cert_path);
        return -1;
    }

    subject = X509_get_subject_name(cert);
    if (!subject) {
        fprintf(stderr, "[CERT] Failed to get Subject from certificate\n");
        goto cleanup;
    }

    idx = X509_NAME_get_index_by_NID(subject, NID_commonName, -1);
    if (idx < 0) {
        fprintf(stderr, "[CERT] CN not found in Subject\n");
        goto cleanup;
    }

    {
        X509_NAME_ENTRY *entry = X509_NAME_get_entry(subject, idx);
        ASN1_STRING *asn1 = X509_NAME_ENTRY_get_data(entry);
        const unsigned char *utf8 = NULL;
        int len = ASN1_STRING_to_UTF8((unsigned char **)&utf8, asn1);

        if (len <= 0 || !utf8) {
            fprintf(stderr, "[CERT] Failed to convert CN to UTF-8\n");
            goto cleanup;
        }

        if ((size_t)len >= cn_buf_len) {
            fprintf(stderr, "[CERT] Buffer is too small for CN (need %d bytes)\n",
                    len + 1);
            OPENSSL_free((void *)utf8);
            goto cleanup;
        }

        memcpy(cn_buf, utf8, (size_t)len);
        cn_buf[len] = '\0';
        OPENSSL_free((void *)utf8);
    }

    printf("[CERT] Subject CN (SN): %s\n", cn_buf);
    rc = 0;

cleanup:
    X509_free(cert);
    return rc;
}
