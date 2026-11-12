// middleware：订单 API 服务，依赖 base-lib 做序列化。
// 雪花 ID 全程保持字符串，避免 Number 转换导致 > 2^53 精度丢失。
const http = require("http");
const { stringify } = require("../base-lib");

// 雪花 ID（> 2^53），数据库里本应是字符串
const orders = {
  "9007199254740993": { userId: "alice", amount: 128 },
  "9007199254740994": { userId: "bob", amount: 256 },
};

http.createServer((req, res) => {
  if (req.url === "/api/orders") {
    // 雪花 ID 直接以字符串透传；Number(id) 会把 9007199254740993/...94 都舍入成 ...92
    const list = Object.keys(orders).map((id) => ({ id, ...orders[id] }));
    res.setHeader("Content-Type", "application/json; charset=utf-8");
    res.end(stringify(list));
  } else if (req.url === "/health") {
    res.end("ok");
  } else {
    res.statusCode = 404;
    res.end("not found");
  }
}).listen(3101, () => console.log("middleware listening :3101"));
