using System;

namespace DeviceRpcClient.Models
{
    /// <summary>
    /// Модель для хранения информации о pending (ожидающих) запросах.
    /// Используется для корреляции запросов и ответов.
    /// </summary>
    public class PendingRequest
    {
        /// <summary>
        /// Тип запроса: "request", "event", и т.д.
        /// </summary>
        public string Type { get; set; }

        /// <summary>
        /// Временная метка отправки запроса (UTC).
        /// </summary>
        public DateTime Timestamp { get; set; }

        /// <summary>
        /// Код метода (для RPC-задач).
        /// </summary>
        public string MethodCode { get; set; }

        /// <summary>
        /// Конструктор по умолчанию.
        /// </summary>
        public PendingRequest()
        {
            Timestamp = DateTime.UtcNow;
        }

        /// <summary>
        /// Конструктор с параметрами.
        /// </summary>
        /// <param name="type">Тип запроса.</param>
        /// <param name="methodCode">Код метода (опционально).</param>
        public PendingRequest(string type, string methodCode = null)
        {
            Type = type;
            MethodCode = methodCode;
            Timestamp = DateTime.UtcNow;
        }

        /// <summary>
        /// Проверка, истёк ли запрос по таймауту.
        /// </summary>
        /// <param name="timeoutSeconds">Таймаут в секундах.</param>
        /// <returns>True, если запрос истёк.</returns>
        public bool IsExpired(int timeoutSeconds = 300)
        {
            return (DateTime.UtcNow - Timestamp).TotalSeconds > timeoutSeconds;
        }

        public override string ToString()
        {
            return $"PendingRequest [Type={Type}, MethodCode={MethodCode}, Timestamp={Timestamp:O}]";
        }
    }
}
