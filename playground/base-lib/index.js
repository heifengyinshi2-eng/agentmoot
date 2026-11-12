// base-lib：JSON 序列化基础库
//
// 大整数（> Number.MAX_SAFE_INTEGER）处理说明：
//   - BigInt：序列化为十进制字符串（如 9007199254740993n -> "9007199254740993"），
//     保证跨语言/跨服务传输时不被 IEEE-754 double 舍入。
//   - 非安全整数 Number：同样输出为字符串，避免下游继续按 double 处理。
//     注意：该 Number 在进入 stringify 之前可能已丢精度（JS 字面量 9007199254740993
//     本身就会被求值为 9007199254740992），base-lib 无法还原；调用方应改用 BigInt
//     或字符串（例如数据库中的雪花 ID 全程保持字符串）。
//   - parse(s, { bigint: true }) 会把安全范围外的纯整数数字字符串还原为 BigInt，
//     使 parse(stringify(x)) 对 BigInt 输入成立。
const DEFAULT_OPTIONS = {
  // bigint: BigInt 的序列化方式，可选 "string"（默认）| "error"
  bigint: "string",
  // unsafeNumber: 非安全整数 Number 的处理，可选 "string"（默认）| "error" | "ignore"
  unsafeNumber: "string",
};

function isUnsafeInteger(v) {
  return typeof v === "number" && Number.isInteger(v) && !Number.isSafeInteger(v);
}

function stringify(obj, options) {
  const opts = Object.assign({}, DEFAULT_OPTIONS, options);
  return JSON.stringify(obj, function (_key, v) {
    if (typeof v === "bigint") {
      if (opts.bigint === "error") {
        throw new RangeError("base-lib.stringify: BigInt 不允许直接序列化（bigint: 'error'）");
      }
      return v.toString();
    }
    if (isUnsafeInteger(v)) {
      if (opts.unsafeNumber === "error") {
        throw new RangeError(
          "base-lib.stringify: 检测到非安全整数 " + v + "（已可能丢精度），请改用 BigInt 或字符串"
        );
      }
      if (opts.unsafeNumber === "string") {
        return String(v);
      }
    }
    return v;
  });
}

// 纯整数字符串：可选还原为 BigInt（仅当超出安全整数范围时）
const INTEGER_RE = /^-?\d+$/;

function parse(s, options) {
  const opts = Object.assign({ bigint: false }, options);
  if (!opts.bigint) {
    return JSON.parse(s);
  }
  return JSON.parse(s, function (_key, v) {
    if (typeof v === "string" && INTEGER_RE.test(v)) {
      let n;
      try {
        n = BigInt(v);
      } catch (_e) {
        return v;
      }
      if (n > BigInt(Number.MAX_SAFE_INTEGER) || n < BigInt(Number.MIN_SAFE_INTEGER)) {
        return n;
      }
    }
    return v;
  });
}

module.exports = { stringify, parse };
