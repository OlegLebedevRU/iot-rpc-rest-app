using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using MQTTnet;
using MQTTnet.Client;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using DeviceRpcClient.Models;

namespace DeviceRpcClient.Handlers
{
    /// <summary>
    /// Обработчик входящих MQTT-сообщений.
    /// Содержит логику маршрутизации и обработки сообщений по топикам.
    /// </summary>
    public class MessageHandler
    {
        private readonly string _serialNumber;
        private readonly Dictionary<string, PendingRequest> _pendingRequests;
        
        // Callback функции для интеграции с DeviceClient
        private readonly Func<string, Task> _sendAckFunc;
        private readonly Func<string, Task> _sendRequestFunc;
        private readonly Func<string, JObject, string, Task> _sendResultFunc;

        // Топики
        private readonly string _topicRsp;
        private readonly string _topicTsk;
        private readonly string _topicCmt;
        private readonly string _topicEva;

        /// <summary>
        /// Конструктор обработчика сообщений.
        /// </summary>
        /// <param name="serialNumber">Серийный номер устройства (SN).</param>
        /// <param name="pendingRequests">Словарь pending-запросов.</param>
        /// <param name="sendAckFunc">Callback для отправки ACK.</param>
        /// <param name="sendRequestFunc">Callback для отправки REQ.</param>
        /// <param name="sendResultFunc">Callback для отправки RES.</param>
        public MessageHandler(
            string serialNumber,
            Dictionary<string, PendingRequest> pendingRequests,
            Func<string, Task> sendAckFunc,
            Func<string, Task> sendRequestFunc,
            Func<string, JObject, string, Task> sendResultFunc)
        {
            _serialNumber = serialNumber;
            _pendingRequests = pendingRequests;
            _sendAckFunc = sendAckFunc;
            _sendRequestFunc = sendRequestFunc;
            _sendResultFunc = sendResultFunc;

            // Инициализация топиков
            _topicRsp = $"srv/{_serialNumber}/rsp";
            _topicTsk = $"srv/{_serialNumber}/tsk";
            _topicCmt = $"srv/{_serialNumber}/cmt";
            _topicEva = $"srv/{_serialNumber}/eva";
        }

        /// <summary>
        /// Основной метод обработки входящих MQTT-сообщений.
        /// </summary>
        /// <param name="args">Аргументы события получения сообщения.</param>
        public async Task HandleMessageAsync(MqttApplicationMessageReceivedEventArgs args)
        {
            try
            {
                var topic = args.ApplicationMessage.Topic;
                
                // Получение payload
                var payload = args.ApplicationMessage.PayloadSegment.Array != null
                    ? Encoding.UTF8.GetString(
                        args.ApplicationMessage.PayloadSegment.Array,
                        args.ApplicationMessage.PayloadSegment.Offset,
                        args.ApplicationMessage.PayloadSegment.Count)
                    : "";

                // Получение correlationData из User Properties (для совместимости с разными реализациями)
                var correlationData = args.ApplicationMessage.UserProperties?
                    .FirstOrDefault(p => p.Name == "correlationData")?.Value ?? "";

                // Альтернативно: проверяем нативное CorrelationData (MQTT 5)
                if (string.IsNullOrEmpty(correlationData) && args.ApplicationMessage.CorrelationData != null)
                {
                    correlationData = Encoding.UTF8.GetString(args.ApplicationMessage.CorrelationData);
                }

                // Собираем все User Properties в словарь
                var userPropertiesDict = args.ApplicationMessage.UserProperties?
                    .ToDictionary(p => p.Name, p => p.Value) ?? new Dictionary<string, string>();

                Console.WriteLine($"[MSG] Получено сообщение: {topic} | Correlation: {correlationData}");

                // Маршрутизация по топикам
                if (topic == _topicTsk)
                {
                    await HandleTaskAnnouncementAsync(correlationData, userPropertiesDict);
                }
                else if (topic == _topicRsp)
                {
                    await HandleTaskResponseAsync(correlationData, payload, userPropertiesDict);
                }
                else if (topic == _topicCmt)
                {
                    await HandleCommitAsync(correlationData, userPropertiesDict);
                }
                else if (topic == _topicEva)
                {
                    await HandleEventAcknowledgementAsync(correlationData, userPropertiesDict);
                }
                else
                {
                    Console.WriteLine($"[WARN] Неизвестный топик: {topic}");
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[ERROR] Ошибка при обработке сообщения: {ex.Message}");
                Console.WriteLine($"[ERROR] StackTrace: {ex.StackTrace}");
            }
        }

        /// <summary>
        /// Обработка анонса задачи (TSK) от сервера (Trigger mode).
        /// </summary>
        private async Task HandleTaskAnnouncementAsync(string correlationData, Dictionary<string, string> userProps)
        {
            var methodCode = userProps.ContainsKey("method_code") ? userProps["method_code"] : "unknown";
            Console.WriteLine($"[TSK] Анонс задачи: correlation={correlationData}, method={methodCode}");

            // Опциональное подтверждение получения задачи
            await _sendAckFunc(correlationData);

            // Запрос параметров задачи
            await _sendRequestFunc(correlationData);
        }

        /// <summary>
        /// Обработка ответа сервера с параметрами задачи (RSP).
        /// </summary>
        private async Task HandleTaskResponseAsync(string correlationData, string payload, Dictionary<string, string> userProps)
        {
            var methodCode = userProps.ContainsKey("method_code") ? userProps["method_code"] : "unknown";

            // Удаляем запрос из pending
            if (_pendingRequests.ContainsKey(correlationData))
            {
                _pendingRequests.Remove(correlationData);
            }

            Console.WriteLine($"[RSP] Параметры задачи получены: method={methodCode}, correlation={correlationData}");
            Console.WriteLine($"[RSP] Payload: {payload}");

            // Парсинг и выполнение задачи
            JObject parameters = null;
            if (!string.IsNullOrEmpty(payload))
            {
                try
                {
                    parameters = JObject.Parse(payload);
                }
                catch (JsonException ex)
                {
                    Console.WriteLine($"[WARN] Не удалось распарсить payload: {ex.Message}");
                    parameters = new JObject();
                }
            }
            else
            {
                parameters = new JObject();
            }

            // Выполнение задачи
            var result = await ExecuteTaskAsync(methodCode, parameters);

            // Отправка результата
            await _sendResultFunc(correlationData, result, methodCode);
        }

        /// <summary>
        /// Обработка подтверждения получения результата (CMT) от сервера.
        /// </summary>
        private Task HandleCommitAsync(string correlationData, Dictionary<string, string> userProps)
        {
            var resultId = userProps.ContainsKey("result_id") ? userProps["result_id"] : "unknown";
            Console.WriteLine($"[CMT] Получено подтверждение: result_id={resultId}, correlation={correlationData}");
            Console.WriteLine($"[CMT] RPC-цикл завершён успешно!");
            
            return Task.CompletedTask;
        }

        /// <summary>
        /// Обработка подтверждения события (EVA) от сервера.
        /// </summary>
        private Task HandleEventAcknowledgementAsync(string correlationData, Dictionary<string, string> userProps)
        {
            Console.WriteLine($"[EVA] Подтверждение события получено: correlation={correlationData}");
            return Task.CompletedTask;
        }

        /// <summary>
        /// Выполнение задачи на устройстве.
        /// ⚠️ Здесь реализуйте вашу бизнес-логику обработки команд!
        /// </summary>
        /// <param name="methodCode">Код метода/команды.</param>
        /// <param name="parameters">Параметры задачи (JSON).</param>
        /// <returns>Результат выполнения (JSON).</returns>
        private async Task<JObject> ExecuteTaskAsync(string methodCode, JObject parameters)
        {
            Console.WriteLine($"[EXEC] Выполнение задачи: method={methodCode}");
            Console.WriteLine($"[EXEC] Параметры: {parameters}");

            // ====================================
            // ⚠️ ЗДЕСЬ РЕАЛИЗУЙТЕ ВАШУ ЛОГИКУ!
            // ====================================
            // Примеры методов:
            // - "51" - Открыть что-то
            // - "52" - Закрыть что-то
            // - "69" - Специальная команда
            // - "3001" - Интерактивная команда (требует WebSocket)
            
            // Пример проверки интерактивных методов (3000-3999)
            if (int.TryParse(methodCode, out int code) && code >= 3000 && code <= 3999)
            {
                // Интерактивные команды — нужен активный WS-клиент
                Console.WriteLine($"[EXEC] Интерактивная команда {code} — проверьте наличие WS-клиента");
                // Если WS-клиент не активен, возвращаем ошибку 500 (fail-fast)
                // return new JObject { ["status"] = "error", ["message"] = "No active WebSocket client" };
            }

            // Имитация выполнения работы
            await Task.Delay(1000);

            // Возвращаем успешный результат
            var result = new JObject
            {
                ["status"] = "completed",
                ["data"] = new JObject
                {
                    ["method"] = methodCode,
                    ["executed_at"] = DateTime.UtcNow.ToString("O"),
                    ["success"] = true
                }
            };

            Console.WriteLine($"[EXEC] Задача выполнена: {result}");
            return result;
        }
    }
}
