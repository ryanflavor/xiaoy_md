# **12\. Error Handling Strategy**

## **CTP Gateway Connection Errors**

* **Strategy**: **Process Supervisor & Restart**. The CTP adapter will run the vnpy gateway in an isolated child process. Upon detecting a failure, the adapter will terminate the old process and start a new one.

## **NATS Publish Failures**

* **Strategy**: The NATS adapter will use an **exponential backoff** retry strategy.

## **"Poison Pill" Messages**

* **Strategy**: All processing steps, especially serialization, will be wrapped in try...except blocks to isolate failing messages, log them, and continue processing the queue, ensuring the service does not crash.

---
