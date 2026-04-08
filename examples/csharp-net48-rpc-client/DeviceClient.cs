using System;
using System.Collections.Generic;
using System.Configuration;
using System.Linq;
using System.Security.Authentication;
using System.Security.Cryptography.X509Certificates;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using MQTTnet;
using MQTTnet.Client;
using MQTTnet.Protocol;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using DeviceRpcClient.Models;
using DeviceRpcClient.Handlers;

namespace DeviceRpcClient
{
    /// <summary>
    /// Основной класс IoT RPC-клиента (Device).
    /// Реализует протокол MQTT 5 для асинхронного RPC-взаимодействия с сервером.
    /// </summary>
    public class DeviceClient : IDisposable
    {
        #region Private Fields

        private readonly string _brokerHost;
        private readonly int _brokerPort;
        private readonly string _clientCertPath;
        private readonly string _clientCertPassword;
        private readonly int _reqPollInterval;
        private readonly int _healthcheckInterval;

        private IMqttClient _mqttClient;
        private MqttClientOptions _mqttOptions;
        private MessageHandler _messageHandler;
        
        private CancellationTokenSource _cancellationTokenSource;
        private readonly Dictionary<string, PendingRequest> _pendingRequests;
        
        private string _serialNumber;
        private bool _isDisposed;

        // Топики (инициализируются после получения SN)
        private string _topicReq;
        private string _topicRes;
        private string _topicEvt;
        private string _topicAck;
        private string _topicRsp;
        private string _topicTsk;
        private string _topicCmt;
        private string _topicEva;

        #endregion

        #region Constructor

        /// <summary>
        /// Создаёт новый экземпляр DeviceClient с настройками из App.config.
        /// </summary>
        public DeviceClient()
        {
            _pendingRequests = new Dictionary<string, PendingRequest>();
            
            // Загрузка конфигурации из App.config
            _brokerHost = ConfigurationManager.AppSettings["BrokerHost"] ?? "your-mqtt-broker.com";
            _brokerPort = int.Parse(ConfigurationManager.AppSettings["BrokerPort"] ?? "8883");
            _clientCertPath = ConfigurationManager.AppSettings["ClientCertPath"] ?? "certificates\\client_cert.pfx";
            _clientCertPassword = ConfigurationManager.AppSettings["ClientCertPassword"] ?? "";
            _reqPollInterval = int.Parse(ConfigurationManager.AppSettings["ReqPollInterval"] ?? "60");
            _healthcheckInterval = int.Parse(ConfigurationManager.AppSettings["HealthcheckInterval"] ?? "300");

            Console.WriteLine($"[CONFIG] Broker: {_brokerHost}:{_brokerPort}");
            Console.WriteLine($"[CONFIG] Certificate: {_clientCertPath}");
            Console.WriteLine($"[CONFIG] Poll interval: {_reqPollInterval}s, Healthcheck: {_healthcheckInterval}s");
        }

        /// <summary>
        /// Создаёт новый экземпляр DeviceClient с явными параметрами.
        /// </summary>
        /// <param name="brokerHost">Адрес MQTT-брокера.</param>
        /// <param name="brokerPort">Порт MQTT-брокера (по умолчанию 8883 для TLS).</param>
        /// <param name="clientCertPath">Путь к PFX-файлу сертификата клиента.</param>
        /// <param name="clientCertPassword">Пароль от сертификата.</param>
        /// <param name="reqPollInterval">Интервал поллинга (секунды).</param>
        /// <param name="healthcheckInterval">Интервал healthcheck (секунды).</param>
        public DeviceClient(
            string brokerHost,
            int brokerPort,
            string clientCertPath,
            string clientCertPassword,
            int reqPollInterval = 60,
            int healthcheckInterval = 300)
        {
            _pendingRequests = new Dictionary<string, PendingRequest>();
            _brokerHost = brokerHost;
            _brokerPort = brokerPort;
            _clientCertPath = clientCertPath;
            _clientCertPassword = clientCertPassword;
            _reqPollInterval = reqPollInterval;
            _healthcheckInterval = healthcheckInterval;
        }

        #endregion

        #region Public Methods

        /// <summary>
        /// Запускает клиент: подключается к брокеру и начинает работу.
        /// </summary>
        public async Task StartAsync()
        {
            Console.WriteLine("[START] Инициализация DeviceClient...");

            // Извлечение серийного номера из сертификата
            _serialNumber = ExtractSerialNumberFromCertificate();
            Console.WriteLine($"[SN] Серийный номер устройства: {_serialNumber}");

            // Инициализация топиков
            InitializeTopics();

            // Инициализация MQTT-клиента
            InitializeMqttClient();

            // Инициализация обработчика сообщений
            _messageHandler = new MessageHandler(
                _serialNumber,
                _pendingRequests,
                SendAckAsync,
                SendRequestAsync,
                SendResultAsync);

            // Подключение к брокеру
            await ConnectAsync();
        }

        /// <summary>
        /// Останавливает клиент и отключается от брокера.
        /// </summary>
        public async Task StopAsync()
        {
            Console.WriteLine("[STOP] Остановка DeviceClient...");
            
            _cancellationTokenSource?.Cancel();
            
            if (_mqttClient?.IsConnected == true)
            {
                await _mqttClient.DisconnectAsync();
            }

            Console.WriteLine("[STOP] DeviceClient остановлен.");
        }

        #endregion

        #region Private Methods - Initialization

        /// <summary>
        /// Извлекает серийный номер (SN) из CN (Common Name) клиентского сертификата.
        /// </summary>
        private string ExtractSerialNumberFromCertificate()
        {
            try
            {
                var cert = new X509Certificate2(_clientCertPath, _clientCertPassword);
                var subject = cert.Subject;

                Console.WriteLine($"[CERT] Subject: {subject}");

                // Извлечение CN из Subject
                var cnPair = subject.Split(',')
                    .Select(part => part.Trim())
                    .FirstOrDefault(part => part.StartsWith("CN=", StringComparison.OrdinalIgnoreCase));

                if (!string.IsNullOrEmpty(cnPair) && cnPair.Length > 3)
                {
                    var sn = cnPair.Substring(3);
                    Console.WriteLine($"[CERT] Извлечён SN из CN: {sn}");
                    return sn;
                }

                throw new InvalidOperationException("Не удалось извлечь CN из сертификата.");
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[ERROR] Ошибка при чтении сертификата: {ex.Message}");
                throw;
            }
        }

        /// <summary>
        /// Инициализирует топики на основе серийного номера.
        /// </summary>
        private void InitializeTopics()
        {
            // Топики для публикации (устройство → сервер)
            _topicReq = $"dev/{_serialNumber}/req";
            _topicRes = $"dev/{_serialNumber}/res";
            _topicEvt = $"dev/{_serialNumber}/evt";
            _topicAck = $"dev/{_serialNumber}/ack";

            // Топики для подписки (сервер → устройство)
            _topicRsp = $"srv/{_serialNumber}/rsp";
            _topicTsk = $"srv/{_serialNumber}/tsk";
            _topicCmt = $"srv/{_serialNumber}/cmt";
            _topicEva = $"srv/{_serialNumber}/eva";

            Console.WriteLine($"[TOPICS] REQ: {_topicReq}, RES: {_topicRes}, EVT: {_topicEvt}");
            Console.WriteLine($"[TOPICS] RSP: {_topicRsp}, TSK: {_topicTsk}, CMT: {_topicCmt}");
        }

        /// <summary>
        /// Инициализирует MQTT-клиент с настройками TLS.
        /// </summary>
        private void InitializeMqttClient()
        {
            var factory = new MqttFactory();
            _mqttClient = factory.CreateMqttClient();

            // Загрузка клиентского сертификата
            var clientCert = new X509Certificate2(
                _clientCertPath,
                _clientCertPassword,
                X509KeyStorageFlags.MachineKeySet | X509KeyStorageFlags.PersistKeySet);

            var tlsOptions = new MqttClientTlsOptions
            {
                UseTls = true,
                ClientCertificatesProvider = new MqttClientCertificatesProvider(clientCert),
                CertificateValidationHandler = context =>
                {
                    // Здесь можно реализовать дополнительную валидацию сертификата сервера
                    Console.WriteLine($"[TLS] Проверка сертификата сервера: {context.Certificate?.Subject}");
                    return true; // Упрощённо: доверяем CA
                },
                SslProtocol = SslProtocols.Tls12
            };

            _mqttOptions = new MqttClientOptionsBuilder()
                .WithClientId(_serialNumber)
                .WithTcpServer(_brokerHost, _brokerPort)
                .WithProtocolVersion(MQTTnet.Formatter.MqttProtocolVersion.V500)
                .WithTlsOptions(tlsOptions)
                .WithCleanSession(true)
                .WithKeepAlivePeriod(TimeSpan.FromSeconds(60))
                .Build();

            // Подписка на события клиента
            _mqttClient.ConnectedAsync += OnConnectedAsync;
            _mqttClient.DisconnectedAsync += OnDisconnectedAsync;
            _mqttClient.ApplicationMessageReceivedAsync += OnMessageReceivedAsync;
        }

        #endregion

        #region Private Methods - MQTT Events

        /// <summary>
        /// Обработчик события подключения к брокеру.
        /// </summary>
        private async Task OnConnectedAsync(MqttClientConnectedEventArgs args)
        {
            Console.WriteLine("[MQTT] Подключено к MQTT-брокеру!");

            // Подписка на топики
            var subscribeOptions = new MqttClientSubscribeOptionsBuilder()
                .WithTopicFilter(_topicRsp, MqttQualityOfServiceLevel.AtLeastOnce)
                .WithTopicFilter(_topicTsk, MqttQualityOfServiceLevel.AtLeastOnce)
                .WithTopicFilter(_topicCmt, MqttQualityOfServiceLevel.AtLeastOnce)
                .WithTopicFilter(_topicEva, MqttQualityOfServiceLevel.AtLeastOnce)
                .Build();

            await _mqttClient.SubscribeAsync(subscribeOptions);
            Console.WriteLine("[MQTT] Подписка на топики выполнена.");

            // Запуск фоновых задач
            _cancellationTokenSource = new CancellationTokenSource();
            _ = Task.Run(() => PollingLoopAsync(_cancellationTokenSource.Token));
            _ = Task.Run(() => HealthcheckLoopAsync(_cancellationTokenSource.Token));

            Console.WriteLine("[MQTT] Фоновые задачи запущены.");
        }

        /// <summary>
        /// Обработчик события отключения от брокера.
        /// </summary>
        private Task OnDisconnectedAsync(MqttClientDisconnectedEventArgs args)
        {
            Console.WriteLine($"[MQTT] Отключено от брокера: {args.Reason}");
            
            if (args.Exception != null)
            {
                Console.WriteLine($"[MQTT] Exception: {args.Exception.Message}");
            }

            // Здесь можно реализовать автоматическое переподключение
            return Task.CompletedTask;
        }

        /// <summary>
        /// Обработчик входящих MQTT-сообщений.
        /// </summary>
        private async Task OnMessageReceivedAsync(MqttApplicationMessageReceivedEventArgs args)
        {
            await _messageHandler.HandleMessageAsync(args);
        }

        #endregion

        #region Private Methods - Connect

        /// <summary>
        /// Подключается к MQTT-брокеру.
        /// </summary>
        private async Task ConnectAsync()
        {
            Console.WriteLine($"[MQTT] Подключение к {_brokerHost}:{_brokerPort}...");

            try
            {
                var result = await _mqttClient.ConnectAsync(_mqttOptions);
                Console.WriteLine($"[MQTT] Результат подключения: {result.ResultCode}");
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[ERROR] Ошибка подключения: {ex.Message}");
                throw;
            }
        }

        #endregion

        #region Private Methods - Messaging

        /// <summary>
        /// Отправляет REQ (запрос параметров задачи или поллинг).
        /// </summary>
        /// <param name="correlationData">UUID корреляции (или null для поллинга).</param>
        public async Task SendRequestAsync(string correlationData = null)
        {
            // Для поллинга используем нулевой UUID
            if (string.IsNullOrEmpty(correlationData))
            {
                correlationData = "00000000-0000-0000-0000-000000000000";
            }

            var message = new MqttApplicationMessageBuilder()
                .WithTopic(_topicReq)
                .WithPayload("")
                .WithQualityOfServiceLevel(MqttQualityOfServiceLevel.AtLeastOnce)
                .WithUserProperty("correlationData", correlationData)
                .Build();

            await _mqttClient.PublishAsync(message);

            // Сохраняем pending-запрос (кроме поллинга)
            if (correlationData != "00000000-0000-0000-0000-000000000000")
            {
                _pendingRequests[correlationData] = new PendingRequest("request");
            }

            Console.WriteLine($"[REQ] Отправлен запрос: correlation={correlationData}");
        }

        /// <summary>
        /// Отправляет ACK (подтверждение получения TSK).
        /// </summary>
        /// <param name="correlationData">UUID корреляции.</param>
        public async Task SendAckAsync(string correlationData)
        {
            var message = new MqttApplicationMessageBuilder()
                .WithTopic(_topicAck)
                .WithPayload("")
                .WithQualityOfServiceLevel(MqttQualityOfServiceLevel.AtLeastOnce)
                .WithUserProperty("correlationData", correlationData)
                .Build();

            await _mqttClient.PublishAsync(message);
            Console.WriteLine($"[ACK] Отправлено подтверждение: correlation={correlationData}");
        }

        /// <summary>
        /// Отправляет RES (результат выполнения задачи).
        /// </summary>
        /// <param name="correlationData">UUID корреляции.</param>
        /// <param name="result">Результат (JSON).</param>
        /// <param name="methodCode">Код метода.</param>
        /// <param name="statusCode">Код статуса (по умолчанию 200).</param>
        /// <param name="extId">Внешний ID (опционально).</param>
        public async Task SendResultAsync(
            string correlationData,
            JObject result,
            string methodCode,
            string statusCode = "200",
            string extId = "")
        {
            var payload = result.ToString(Formatting.None);

            var messageBuilder = new MqttApplicationMessageBuilder()
                .WithTopic(_topicRes)
                .WithPayload(payload)
                .WithQualityOfServiceLevel(MqttQualityOfServiceLevel.AtLeastOnce)
                .WithUserProperty("correlationData", correlationData)
                .WithUserProperty("status_code", statusCode);

            if (!string.IsNullOrEmpty(extId))
            {
                messageBuilder.WithUserProperty("ext_id", extId);
            }

            await _mqttClient.PublishAsync(messageBuilder.Build());
            Console.WriteLine($"[RES] Результат отправлен: correlation={correlationData}, status={statusCode}");
        }

        /// <summary>
        /// Отправляет EVT (асинхронное событие).
        /// </summary>
        /// <param name="eventTypeCode">Код типа события.</param>
        /// <param name="eventData">Данные события.</param>
        /// <param name="devEventId">Внутренний ID события на устройстве.</param>
        public async Task SendEventAsync(int eventTypeCode, object eventData, string devEventId = "")
        {
            var correlationId = Guid.NewGuid().ToString();
            var payload = JsonConvert.SerializeObject(eventData);
            var timestamp = DateTimeOffset.UtcNow.ToUnixTimeSeconds().ToString();

            if (string.IsNullOrEmpty(devEventId))
            {
                devEventId = new Random().Next(1000, 99999).ToString();
            }

            var message = new MqttApplicationMessageBuilder()
                .WithTopic(_topicEvt)
                .WithPayload(payload)
                .WithQualityOfServiceLevel(MqttQualityOfServiceLevel.AtLeastOnce)
                .WithUserProperty("correlationData", correlationId)
                .WithUserProperty("event_type_code", eventTypeCode.ToString())
                .WithUserProperty("dev_event_id", devEventId)
                .WithUserProperty("dev_timestamp", timestamp)
                .Build();

            await _mqttClient.PublishAsync(message);
            Console.WriteLine($"[EVT] Событие отправлено: type={eventTypeCode}, correlation={correlationId}");
        }

        #endregion

        #region Private Methods - Background Loops

        /// <summary>
        /// Цикл поллинга задач (Polling mode).
        /// </summary>
        private async Task PollingLoopAsync(CancellationToken cancellationToken)
        {
            Console.WriteLine($"[POLL] Запущен цикл поллинга (интервал: {_reqPollInterval} сек)");

            while (!cancellationToken.IsCancellationRequested)
            {
                try
                {
                    await SendRequestAsync();
                }
                catch (Exception ex)
                {
                    Console.WriteLine($"[POLL] Ошибка в цикле поллинга: {ex.Message}");
                }

                try
                {
                    await Task.Delay(TimeSpan.FromSeconds(_reqPollInterval), cancellationToken);
                }
                catch (TaskCanceledException)
                {
                    break;
                }
            }

            Console.WriteLine("[POLL] Цикл поллинга остановлен.");
        }

        /// <summary>
        /// Цикл healthcheck (отправка keep-alive событий).
        /// </summary>
        private async Task HealthcheckLoopAsync(CancellationToken cancellationToken)
        {
            Console.WriteLine($"[HEALTH] Запущен цикл healthcheck (интервал: {_healthcheckInterval} сек)");

            while (!cancellationToken.IsCancellationRequested)
            {
                try
                {
                    // Отправка события healthcheck (код 44)
                    await SendEventAsync(44, CreateHealthcheckPayload());
                }
                catch (Exception ex)
                {
                    Console.WriteLine($"[HEALTH] Ошибка в цикле healthcheck: {ex.Message}");
                }

                try
                {
                    await Task.Delay(TimeSpan.FromSeconds(_healthcheckInterval), cancellationToken);
                }
                catch (TaskCanceledException)
                {
                    break;
                }
            }

            Console.WriteLine("[HEALTH] Цикл healthcheck остановлен.");
        }

        /// <summary>
        /// Создаёт payload для healthcheck-события.
        /// </summary>
        private object CreateHealthcheckPayload()
        {
            return new
            {
                _101 = new Random().Next(1000, 99999), // Внутренний ID события
                _102 = DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ"),
                _200 = 44, // Код типа события (healthcheck)
                _300 = new[]
                {
                    new
                    {
                        _310 = "1.0.0",              // Версия ПО
                        _311 = 13,                    // Тип устройства
                        _312 = 0,                     // Статус
                        _313 = 65740,                 // Uptime (секунды)
                        _314 = GetMacAddress(),       // MAC-адрес
                        _316 = 492,                   // Свободная память (KB)
                        _317 = 26598,                 // Всего памяти (KB)
                        _323 = GetLocalIpAddress(),   // Локальный IP
                        _324 = _serialNumber,         // Серийный номер
                        _325 = GetLocalIpAddress(),   // Внешний IP (может отличаться)
                        _329 = 1,                     // Количество подключений
                        _330 = 21,                    // Сигнал WiFi (dBm)
                        _331 = 0,                     // Ошибки
                        _332 = 2,                     // Канал WiFi
                        _333 = 1,                     // Режим работы
                        _336 = 5                      // Дополнительный параметр
                    }
                }
            };
        }

        /// <summary>
        /// Получает MAC-адрес первого сетевого интерфейса.
        /// </summary>
        private string GetMacAddress()
        {
            try
            {
                var nic = System.Net.NetworkInformation.NetworkInterface.GetAllNetworkInterfaces()
                    .FirstOrDefault(n => n.OperationalStatus == System.Net.NetworkInformation.OperationalStatus.Up);
                
                if (nic != null)
                {
                    return string.Join(":", nic.GetPhysicalAddress().GetAddressBytes().Select(b => b.ToString("x2")));
                }
            }
            catch { }
            
            return "00:00:00:00:00:00";
        }

        /// <summary>
        /// Получает локальный IP-адрес.
        /// </summary>
        private string GetLocalIpAddress()
        {
            try
            {
                var host = System.Net.Dns.GetHostEntry(System.Net.Dns.GetHostName());
                var ip = host.AddressList.FirstOrDefault(a => a.AddressFamily == System.Net.Sockets.AddressFamily.InterNetwork);
                return ip?.ToString() ?? "127.0.0.1";
            }
            catch
            {
                return "127.0.0.1";
            }
        }

        #endregion

        #region IDisposable

        public void Dispose()
        {
            Dispose(true);
            GC.SuppressFinalize(this);
        }

        protected virtual void Dispose(bool disposing)
        {
            if (_isDisposed) return;

            if (disposing)
            {
                _cancellationTokenSource?.Cancel();
                _cancellationTokenSource?.Dispose();
                _mqttClient?.Dispose();
            }

            _isDisposed = true;
        }

        #endregion
    }

    /// <summary>
    /// Провайдер клиентских сертификатов для MQTTnet.
    /// </summary>
    internal class MqttClientCertificatesProvider : IMqttClientCertificatesProvider
    {
        private readonly X509Certificate2 _certificate;

        public MqttClientCertificatesProvider(X509Certificate2 certificate)
        {
            _certificate = certificate;
        }

        public X509CertificateCollection GetCertificates()
        {
            return new X509CertificateCollection { _certificate };
        }
    }
}
