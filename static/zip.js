/* 极简 ZIP 打包器（store 模式，不压缩）：只用于把二维码 PNG 批量打包下载。
 * 零第三方依赖，纯浏览器标准 API；PNG 由 qrcodejs 生成后以 dataURL 传入。
 * 结构是 local file header + central directory + EOCD，CRC32 逐文件计算。
 */
(function () {
  const enc = new TextEncoder();

  function crc32(bytes) {
    let crc = 0xffffffff;
    for (let i = 0; i < bytes.length; i++) {
      crc ^= bytes[i];
      for (let j = 0; j < 8; j++) crc = (crc >>> 1) ^ (0xEDB88320 & -(crc & 1));
    }
    return (crc ^ 0xffffffff) >>> 0;
  }

  const u16 = n => [n & 255, (n >>> 8) & 255];
  const u32 = n => [n & 255, (n >>> 8) & 255, (n >>> 16) & 255, (n >>> 24) & 255];

  function pngBytes(dataUrl) {
    const b64 = String(dataUrl || '').split(',')[1] || '';
    const bin = atob(b64);
    const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }

  function safeName(name) {
    return (String(name || 'qrcode').replace(/[^\w\u4e00-\u9fa5.-]+/g, '_').slice(0, 60)) || 'qrcode';
  }

  function build(files) {
    const local = [], central = [];
    let offset = 0;
    files.forEach(f => {
      const name = enc.encode(f.name), data = f.data, crc = crc32(data);
      const head = [
        ...u32(0x04034b50), ...u16(20), ...u16(0x0800), ...u16(0), ...u16(0), ...u16(0),
        ...u32(crc), ...u32(data.length), ...u32(data.length),
        ...u16(name.length), ...u16(0),
      ];
      local.push(...head, ...name, ...data);
      const cen = [
        ...u32(0x02014b50), ...u16(20), ...u16(20), ...u16(0x0800), ...u16(0),
        ...u16(0), ...u16(0), ...u32(crc), ...u32(data.length), ...u32(data.length),
        ...u16(name.length), ...u16(0), ...u16(0), ...u16(0), ...u16(0),
        ...u32(0), ...u32(offset),
      ];
      central.push(...cen, ...name);
      offset += head.length + name.length + data.length;
    });
    const end = [
      ...u32(0x06054b50), ...u16(0), ...u16(0),
      ...u16(files.length), ...u16(files.length),
      ...u32(central.length), ...u32(offset), ...u16(0),
    ];
    return new Blob([new Uint8Array(local), new Uint8Array(central), new Uint8Array(end)],
      { type: 'application/zip' });
  }

  window.LinkLabZip = {
    fromDataUrls(files) {
      return build(files.map(f => ({ name: safeName(f.name) + '.png', data: pngBytes(f.dataUrl) })));
    },
    download(blob, filename) {
      const a = document.createElement('a');
      const url = URL.createObjectURL(blob);
      a.href = url;
      a.download = filename || 'LinkLab-二维码.zip';
      document.body.append(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 5000);
    },
  };
})();
