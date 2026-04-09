#if defined(_WIN32)
/*
 * OpenSSL на Windows может требовать символ OPENSSL_Applink при работе
 * с PEM-файлами и стандартным файловым API. Это особенно важно, когда
 * приложение запускается с OpenSSL DLL, ожидающими applink-мост.
 */
#include <openssl/applink.c>
#endif


