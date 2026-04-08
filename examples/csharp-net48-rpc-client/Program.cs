using System;
using System.Threading.Tasks;

namespace DeviceRpcClient
{
    /// <summary>
    /// Точка входа в приложение IoT RPC Device Client.
    /// </summary>
    class Program
    {
        static async Task Main(string[] args)
        {
            Console.OutputEncoding = System.Text.Encoding.UTF8;
            
            Console.WriteLine("╔══════════════════════════════════════════════════════════════╗");
            Console.WriteLine("║           IoT RPC Device Client (.NET Framework 4.8)         ║");
            Console.WriteLine("║               MQTT 5.0 | TLS | Mutual Auth                   ║");
            Console.WriteLine("╚══════════════════════════════════════════════════════════════╝");
            Console.WriteLine();

            DeviceClient client = null;

            try
            {
                // Создание клиента с настройками из App.config
                client = new DeviceClient();

                // Или с явными параметрами:
                // client = new DeviceClient(
                //     brokerHost: "your-mqtt-broker.com",
                //     brokerPort: 8883,
                //     clientCertPath: @"certificates\client_cert.pfx",
                //     clientCertPassword: "your-password",
                //     reqPollInterval: 60,
                //     healthcheckInterval: 300);

                // Запуск клиента
                await client.StartAsync();

                Console.WriteLine();
                Console.WriteLine("════════════════════════════════════════════════════════════════");
                Console.WriteLine("  Клиент запущен и работает. Нажмите любую клавишу для выхода.");
                Console.WriteLine("════════════════════════════════════════════════════════════════");
                Console.WriteLine();

                // Ожидание ввода пользователя
                Console.ReadKey(intercept: true);

                // Остановка клиента
                await client.StopAsync();
            }
            catch (Exception ex)
            {
                Console.WriteLine();
                Console.WriteLine($"[FATAL] Критическая ошибка: {ex.Message}");
                Console.WriteLine($"[FATAL] StackTrace: {ex.StackTrace}");
                Console.WriteLine();
                Console.WriteLine("Нажмите любую клавишу для выхода...");
                Console.ReadKey();
            }
            finally
            {
                client?.Dispose();
            }
        }
    }
}
