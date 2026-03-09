# Документация: Получение и использование подписанного сертификата

## Общее описание

Данный сервис предоставляет возможность регистрации устройства и получения клиентского сертификата в формате PFX. Процесс включает:
- Генерацию приватного ключа и CSR (Certificate Signing Request).
- Отправку CSR на внешний CA.
- Получение подписанного сертификата и цепочки доверия (CA).
- Формирование PFX-файла (`.pfx` или `.p12`) с паролем.
- Возврат base64-кодированного PFX клиенту.

---

## Формат запроса

Клиент отправляет GET-запрос с параметром:
````get
/api/v1/legacy/cert?cert={escaped_pem}
````

Где `escaped_pem` — URL-закодированный PEM-сертификат устройства (например, из TLS handshake).

---

## Этапы обработки на сервере

### 1. Извлечение device_id
Сервер парсит сертификат и извлекает поле `OU` (Organizational Unit), например: `OU=Device0012345`.  
Из него извлекаются цифры — это `device_id`.

### 2. Генерация Serial Number (SN)
Если устройство с таким `device_id` ещё не зарегистрировано, генерируется уникальный SN по шаблону:
````
a{platform}b{device_part}c{random_part}d{date_part}
````

Пример: `a4b0012345c58732d250324`

Где:
- `platform = 4`
- `device_part = 0012345` (7 цифр)
- `random_part = 5 цифр, первая ≠ 0`
- `date_part = ДДММГГ`

### 3. Генерация ключа и CSR
Генерируется RSA-ключ (2048 бит) и CSR с полями:
- `CN = <serial_number>`
- `O = Leo4`
- `OU = <device_part>`
- `C = RU`
- SAN (Subject Alternative Name):
  - DNS: `Leo4-<device_part>.ru`
  - Email: `<device_part>@leo4.ru`

---

## Запрос к CA

### Заголовки:
    X-SSL-Client-CSR: {urlencoded_csr} X-SSL-Client-Exp-Days: 365

### Ожидаемый ответ от CA (формат JSON)
````json
{ 
  "cert": "-----BEGIN CERTIFICATE-----\n...\n-----END CERTIFICATE-----", 
  "ca_pem": "-----BEGIN CERTIFICATE-----\n...\n-----END CERTIFICATE-----", 
  "not_valid_before": "2025-04-05 10:00:00", 
  "not_valid_after": "2026-04-05 10:00:00", 
  "valid_days": 365, 
  "sn": "a4b0012345c58732d250324", 
  "device_id": 12345
}
````

> ⚠️ Поля `cert` и `ca_pem` — **URL-encoded** строки PEM.

---

## Формирование PFX

На основе:
- Сгенерированного приватного ключа
- Подписанного сертификата (`cert`)
- Цепочки CA (`ca_pem`)

Создаётся PFX-файл с паролем формата:  
`pfx-{device_id}-{4_цифры}` → например: `pfx-12345-7890`

PFX кодируется в **base64** и возвращается клиенту.

---

## Ответ сервера (JSON)
````json 
{
  "pfx": "UEsDBBQAAAAIA...", 
  "pfx_password": "pfx-12345-7890", 
  "not_valid_before": "2025-04-05T10:00:00", 
  "not_valid_after": "2026-04-05T10:00:00", 
  "valid_days": 365, 
  "sn": "a4b0012345c58732d250324", 
  "device_id": 12345, 
  "days_left": 365
}
````

---

## Клиент: как сохранить PFX-файл

После получения `pfx` (base64) и `pfx_password`, клиент должен:

1. Декодировать base64 → бинарные данные.
2. Сохранить как файл `.pfx`.
3. Использовать пароль для импорта.

---

### ✅ Пример на Python
````python
import base64
#Полученные данные от сервера
pfx_b64 = "UEsDBBQAAAAIA..." # ваша строка base64 
pfx_password = "pfx-12345-7890"
#Декодируем
pfx_data = base64.b64decode(pfx_b64)
#Сохраняем в файл
with open("client_certificate.pfx", "wb") as f: f.write(pfx_data)
print("PFX сохранён. Пароль:", pfx_password)
````

---

### ✅ Пример на C#
````csharp
using System; using System.IO;
class Program { static void Main() { 
string pfxBase64 = "UEsDBBQAAAAIA..."; // ваша строка base64 
string password = "pfx-12345-7890";
    try
    {
        byte[] pfxData = Convert.FromBase64String(pfxBase64);
        File.WriteAllBytes("client_certificate.pfx", pfxData);
        Console.WriteLine("PFX сохранён. Пароль: " + password);
    }
    catch (FormatException)
    {
        Console.WriteLine("Ошибка: неверный формат base64.");
    }
    catch (Exception ex)
    {
        Console.WriteLine("Ошибка: " + ex.Message);
    }
}
}
````

---

## Проверка PFX (через OpenSSL)
````bash
 openssl pkcs12 -info -in client_certificate.pfx -nodes
 ````
> Будет запрошен пароль.

---

## Ошибки

| Ошибка | Причина |
|-------|--------|
| `No client certificate provided` | Не передан параметр `cert` |
| `Could not extract device_number` | Не найдено число в OU сертификата |
| `CA request failed` | Ошибка соединения с CA |
| `Invalid response from CA` | CA вернул не JSON |
| `Incomplete response from CA` | В ответе CA не хватает полей |
| `Malformed PEM encoding` | Ошибка при URL-decode сертификата |
| `Invalid date format in CA response` | Неверный формат даты |

---

## Логирование

Все этапы логируются через `logging.getLogger(__name__)`. Уровни:
- `log.error()` — критические ошибки
- `log.info()` — регистрация нового устройства

---

## Безопасность

- Приватный ключ **никогда не сохраняется** в БД.
- PFX передаётся один раз, в зашифрованном виде (HTTPS).
- Пароль генерируется одноразово.
- Все данные обрабатываются в памяти.

---

## Требования

- Python 3.9+
- `cryptography`, `httpx`, `sqlalchemy`, `base64`, `urllib.parse`
- Доступ к CA по `settings.leo4.cert_url`
- База данных PostgreSQL (для хранения `device_id` ↔ `serial_number`)