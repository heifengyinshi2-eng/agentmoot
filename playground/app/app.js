// app：面向用户的订单站点，依赖 middleware 的 /api/orders。
const http = require("http");

http.createServer((req, res) => {
  if (req.url === "/") {
    http.get("http://127.0.0.1:3101/api/orders", (r) => {
      let data = "";
      r.on("data", (c) => (data += c));
      r.on("end", () => {
        res.setHeader("Content-Type", "text/html; charset=utf-8");
        res.end("<h1>订单列表</h1><pre>" + data + "</pre>");
      });
    }).on("error", () => {
      res.statusCode = 502;
      res.end("middleware 不可用");
    });
  } else if (req.url === "/health") {
    res.end("ok");
  } else {
    res.statusCode = 404;
    res.end("not found");
  }
}).listen(3100, () => console.log("app listening :3100"));
