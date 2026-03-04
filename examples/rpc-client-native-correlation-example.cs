/*
⚠️ Примечание: MQTTnet v4.5.3 — последняя версия с поддержкой .NET Framework 4.8.
Добавьте в .csproj:
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net48</TargetFramework>
  </PropertyGroup>

  <ItemGroup>
    <PackageReference Include="MQTTnet" Version="4.5.3" />
  </ItemGroup>
</Project>
Подготовка сертификата

Убедитесь, что ваш .pfx файл содержит закрытый ключ.
Файл должен быть добавлен в проект и скопирован в выходную директорию.
CN сертификата должен совпадать с SN.

Особенности реализации
Функция
Реализация
MQTT 5
Используется через WithProtocolVersion(MQTTnet.Formatter.MqttProtocolVersion.V500)
User Properties
Через .WithUserProperty(name, value)
⚠️ Correlation Data Передаётся нативно
⚠️ builder.WithCorrelationData(correlationData)
⚠️ обратить внимание и добавить адаптацию на стороне сервера.

TLS аутентификация
Через PFX-сертификат с закрытым ключом
Асинхронность
На базе async/await, Task.Run
События
SendEvent() с кодом 44 — healthcheck

Извлечение SN из CN
Добавлен метод ExtractSerialNumberFromCertificate()
Чтение .pfx
Сертификат загружается из файла с паролем
Парсинг CN
Из строки Subject извлекается часть CN=...
Использование SN
Как client_id и в построении топиков

🔐 Требования
Файл .pfx должен содержать закрытый ключ
Пароль от .pfx указан в ClientCertPassword
CN должен быть первым элементом или явно указан
📌 Пример содержимого Subject
CN=a3b1234567c10221d290825, O=MyCompany, C=RU
→ Извлекается a3b1234567c10221d290825
*/
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net.Security;
using System.Security.Cryptography.X509Certificates;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;
using MQTTnet;
using MQTTnet.Client;
using MQTTnet.Client.Options;
using MQTTnet.Protocol;

namespace DeviceClient
{
    class Program
    {
        // Константы
        private const string BrokerHost = "your-mqtt-broker.com";
        private const int BrokerPort = 8883;
        private const string ClientCertPath = @"path\to\client_cert.pfx"; // PFX/PKCS#12
        private const string ClientCertPassword = "password"; // Пароль от сертификата

        // Извлечение SN из CN сертификата
        private static readonly string SN = ExtractSerialNumberFromCertificate();

        private static string ExtractSerialNumberFromCertificate()
        {
            try
            {
                var cert = new X509Certificate2(ClientCertPath, ClientCertPassword);
                var cn = cert.Subject;

                var cnPair = cn.Split(',')
                    .Select(part => part.Trim())
                    .FirstOrDefault(part => part.StartsWith("CN="));

                if (cnPair != null && cnPair.Length > 3)
                {
                    var sn = cnPair.Substring(3); // Убираем "CN="
                    Console.WriteLine($"Извлечённый SN из сертификата (CN): {sn}");
                    return sn;
                }

                throw new InvalidOperationException("Не удалось извлечь CN из сертификата.");
            }
            catch (Exception ex)
            {
                Console.WriteLine($"Ошибка при чтении сертификата: {ex.Message}");
                throw;
            }
        }

        // Топики
        private static readonly string TopicReq = $"dev/{SN}/req";
        private static readonly string TopicRes = $"dev/{SN}/res";
        private static readonly string TopicEvt = $"dev/{SN}/evt";
        private static readonly string TopicAck = $"dev/{SN}/ack";

        private static readonly string TopicRsp = $"srv/{SN}/rsp";
        private static readonly string TopicTsk = $"srv/{SN}/tsk";
        private static readonly string TopicCmt = $"srv/{SN}/cmt";
        private static readonly string TopicEva = $"srv/{SN}/eva";

        // Таймеры (в секундах)
        private const int ReqPollInterval = 60;
        private const int HealthcheckInterval = 300;

        private static IMqttClient _mqttClient;
        private static Dictionary<string, PendingRequest> _pendingRequests = new Dictionary<string, PendingRequest>();

        static async Task Main(string[] args)
        {
            await StartClient();
            Console.WriteLine("Нажмите любую клавишу для выхода...");
            Console.ReadKey();
        }

        public static async Task StartClient()
        {
            var factory = new MqttFactory();
            _mqttClient = factory.CreateMqttClient();

            var options = new MqttClientOptionsBuilder()
                .WithClientId(SN)
                .WithTcpServer(BrokerHost, BrokerPort)
                .WithProtocolVersion(MQTTnet.Formatter.MqttProtocolVersion.V500)
                .WithTlsOptions(new MqttClientOptionsBuilderTlsParameters
                {
                    UseTls = true,
                    Certificates = LoadClientCertificate(),
                    CertificateValidationHandler = context => ValidateServerCertificate(context.Certificate),
                    SslProtocol = System.Security.Authentication.SslProtocols.Tls12
                })
                .Build();

            _mqttClient.UseConnectedHandler(async e =>
            {
                Console.WriteLine("Подключено к MQTT брокеру");

                await _mqttClient.SubscribeAsync(new[]
                {
                    new TopicFilterBuilder().WithTopic(TopicRsp).Build(),
                    new TopicFilterBuilder().WithTopic(TopicTsk).Build(),
                    new TopicFilterBuilder().WithTopic(TopicCmt).Build()
                });

                _ = Task.Run(PollingLoop);
                _ = Task.Run(HealthcheckLoop);
            });

            _mqttClient.UseDisconnectedHandler(e =>
            {
                Console.WriteLine("Отключено от MQTT брокера");
            });

            _mqttClient.UseApplicationMessageReceivedHandler(async e =>
            {
                await HandleMessage(e);
            });

            await _mqttClient.ConnectAsync(options);
        }

        private static X509CertificateCollection LoadClientCertificate()
        {
            var cert = new X509Certificate2(ClientCertPath, ClientCertPassword, X509KeyStorageFlags.MachineKeySet | X509KeyStorageFlags.PersistKeySet);
            var certCollection = new X509CertificateCollection { cert };
            return certCollection;
        }

        private static bool ValidateServerCertificate(object certificate)
        {
            var cert = certificate as X509Certificate2;
            if (cert == null) return false;
            return true;
        }

        private static async Task HandleMessage(MqttApplicationMessageReceivedEventArgs e)
        {
            try
            {
                var topic = e.ApplicationMessage.Topic;
                var payload = e.ApplicationMessage.PayloadSegment.Array != null
                    ? Encoding.UTF8.GetString(e.ApplicationMessage.PayloadSegment.Array, e.ApplicationMessage.PayloadSegment.Offset, e.ApplicationMessage.PayloadSegment.Count)
                    : "";

                // Теперь используем настоящий CorrelationData, а не user property
                var correlationData = e.ApplicationMessage.CorrelationData?.ToString() ?? "";
                var userPropsDict = e.ApplicationMessage.UserProperties?.ToDictionary(p => p.Name, p => p.Value) ?? new Dictionary<string, string>();

                Console.WriteLine($"Получено сообщение: {topic} | Correlation: {correlationData}");

                switch (topic)
                {
                    case var t when t == TopicTsk:
                        await HandleTaskAnnouncement(correlationData, userPropsDict);
                        break;
                    case var t when t == TopicRsp:
                        await HandleTaskResponse(correlationData, payload, userPropsDict);
                        break;
                    case var t when t == TopicCmt:
                        await HandleCommit(correlationData, userPropsDict);
                        break;
                    default:
                        Console.WriteLine($"Неизвестный топик: {topic}");
                        break;
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"Ошибка при обработке сообщения: {ex.Message}");
            }
        }

        private static async Task HandleTaskAnnouncement(string correlationData, Dictionary<string, string> userProps)
        {
            var methodCode = userProps.GetValueOrDefault("method_code");
            Console.WriteLine($"Анонс задачи: correlation={correlationData}, method={methodCode}");

            await SendAck(correlationData);
            await SendRequest(correlationData);
        }

        private static async Task HandleTaskResponse(string correlationData, string payload, Dictionary<string, string> userProps)
        {
            var methodCode = userProps.GetValueOrDefault("method_code");
            if (_pendingRequests.TryGetValue(correlationData, out _))
                _pendingRequests.Remove(correlationData);

            Console.WriteLine($"Параметры задачи получены: method={methodCode}, correlation={correlationData}");

            var result = await ExecuteTask(methodCode, JsonSerializer.Deserialize<JsonElement>(payload));
            await SendResult(correlationData, result, methodCode);
        }

        private static async Task HandleCommit(string correlationData, Dictionary<string, string> userProps)
        {
            var resultId = userProps.GetValueOrDefault("result_id");
            Console.WriteLine($"Получено подтверждение cmt: result_id={resultId}, correlation={correlationData}");
        }

        private static async Task<JsonElement> ExecuteTask(string methodCode, JsonElement parameters)
        {
            Console.WriteLine($"Выполнение задачи: method={methodCode}, params={parameters}");
            await Task.Delay(1000);
            using var doc = JsonDocument.Parse("{\"status\": \"completed\", \"data\": \"success\"}");
            return doc.RootElement.Clone();
        }

        private static async Task SendRequest(string correlationData = null)
        {
            if (string.IsNullOrEmpty(correlationData))
                correlationData = "00000000-0000-0000-0000-000000000000";

            var builder = new MqttApplicationMessageBuilder()
                .WithTopic(TopicReq)
                .WithPayload("")
                .WithQualityOfServiceLevel(MqttQualityOfServiceLevel.AtLeastOnce);

            // Устанавливаем CorrelationData как нативное свойство MQTT 5
            var props = builder.WithPayloadFormatIndicator(MqttPayloadFormatIndicator.Unspecified).Build().Properties;
            props.CorrelationData = Encoding.UTF8.GetBytes(correlationData);
            builder.WithUserProperties(props.UserProperties); // Сохраняем другие свойства
            builder.WithCorrelationData(correlationData); // ← Настоящее CorrelationData

            await _mqttClient.PublishAsync(builder.Build());

            _pendingRequests[correlationData] = new PendingRequest
            {
                Type = "request",
                Timestamp = DateTime.UtcNow
            };

            Console.WriteLine($"Отправлен запрос: correlation={correlationData}");
        }

        private static async Task SendAck(string correlationData)
        {
            var builder = new MqttApplicationMessageBuilder()
                .WithTopic(TopicAck)
                .WithPayload("")
                .WithQualityOfServiceLevel(MqttQualityOfServiceLevel.AtLeastOnce)
                .WithCorrelationData(correlationData); // ← Настоящее CorrelationData

            await _mqttClient.PublishAsync(builder.Build());
            Console.WriteLine($"Отправлен ACK: correlation={correlationData}");
        }

        private static async Task SendResult(string correlationData, JsonElement result, string methodCode)
        {
            var payload = JsonSerializer.Serialize(result, new JsonSerializerOptions { WriteIndented = false });

            var builder = new MqttApplicationMessageBuilder()
                .WithTopic(TopicRes)
                .WithPayload(payload)
                .WithQualityOfServiceLevel(MqttQualityOfServiceLevel.AtLeastOnce)
                .WithCorrelationData(correlationData) // ← Настоящее CorrelationData
                .WithUserProperty("status_code", "200")
                .WithUserProperty("ext_id", "12345");

            await _mqttClient.PublishAsync(builder.Build());
            Console.WriteLine($"Результат отправлен: correlation={correlationData}");
        }

        private static async Task SendEvent(int eventTypeCode, object eventData)
        {
            var eventId = Guid.NewGuid().ToString();
            var payload = JsonSerializer.Serialize(eventData);

            var builder = new MqttApplicationMessageBuilder()
                .WithTopic(TopicEvt)
                .WithPayload(payload)
                .WithQualityOfServiceLevel(MqttQualityOfServiceLevel.AtLeastOnce)
                .WithCorrelationData(eventId) // ← Настоящее CorrelationData
                .WithUserProperty("event_type_code", eventTypeCode.ToString())
                .WithUserProperty("dev_event_id", "1001")
                .WithUserProperty("dev_timestamp", DateTimeOffset.UtcNow.ToUnixTimeSeconds().ToString());

            await _mqttClient.PublishAsync(builder.Build());
            Console.WriteLine($"Событие отправлено: type={eventTypeCode}, correlation={eventId}");
        }

        private static async Task PollingLoop()
        {
            while (true)
            {
                try
                {
                    await SendRequest();
                }
                catch (Exception ex)
                {
                    Console.WriteLine($"Ошибка в polling loop: {ex.Message}");
                }
                await Task.Delay(TimeSpan.FromSeconds(ReqPollInterval));
            }
        }

        private static async Task HealthcheckLoop()
        {
            while (true)
            {
                try
                {
                    await SendEvent(44, new
                    {
                        _101 = 1047,
                        _102 = DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ"),
                        _200 = 44,
                        _300 = new[]
                        {
                            new
                            {
                                _310 = "1.04.025",
                                _311 = 13,
                                _312 = 0,
                                _313 = 65740,
                                _314 = "cc:db:a7:1e:56:4b",
                                _316 = 492,
                                _317 = 26598,
                                _323 = "192.168.1.101",
                                _324 = "a1b21c22589d100424",
                                _325 = "192.168.8.101",
                                _329 = 1,
                                _330 = 21,
                                _331 = 0,
                                _332 = 2,
                                _333 = 1,
                                _336 = 5
                            }
                        }
                    });
                }
                catch (Exception ex)
                {
                    Console.WriteLine($"Ошибка в healthcheck loop: {ex.Message}");
                }
                await Task.Delay(TimeSpan.FromSeconds(HealthcheckInterval));
            }
        }
    }

    public class PendingRequest
    {
        public string Type { get; set; }
        public DateTime Timestamp { get; set; }
    }
}