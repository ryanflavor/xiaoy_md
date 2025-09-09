# **12\. Error Handling Strategy**

## **CTP Gateway Connection Errors**

* **Strategy**: **Thread Supervisor & Restart**. The CTP adapter runs the vnpy gateway in an isolated thread. Upon detecting a disconnection or failure, the adapter will spawn a fresh session thread for the next attempt (required for CTP reconnection). The executor can be reused; what must be new is the session thread.

## **NATS Publish Failures**

* **Strategy**: The NATS adapter will use an **exponential backoff** retry strategy.

## **"Poison Pill" Messages**

* **Strategy**: All processing steps, especially serialization, will be wrapped in try...except blocks to isolate failing messages, log them, and continue processing the queue, ensuring the service does not crash.

---
