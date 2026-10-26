// Мини-canvas и заглушки браузера для тестов: ровно те методы, которые
// использует koma-web (nearest scaling). Лежит рядом с тестами, а не в /tmp:
// /tmp не переживает перезапуск песочницы, и все тесты падали с MODULE_NOT_FOUND.
class Ctx {
  constructor(c){ this.c=c; this.imageSmoothingEnabled=true; this.imageSmoothingQuality='high'; this.m=null; }
  setTransform(){}
  translate(){} rotate(){}
  drawImage(src, ...a){
    let sx=0,sy=0,sw=src.width,sh=src.height,dx,dy,dw,dh;
    if(a.length===2){ dx=a[0]; dy=a[1]; dw=sw; dh=sh; }
    else if(a.length===4){ dx=a[0]; dy=a[1]; dw=a[2]; dh=a[3]; }
    else { sx=a[0]; sy=a[1]; sw=a[2]; sh=a[3]; dx=a[4]; dy=a[5]; dw=a[6]; dh=a[7]; }
    for(let y=0;y<dh;y++)for(let x=0;x<dw;x++){
      const px=dx+x|0, py=dy+y|0;
      if(px<0||py<0||px>=this.c.width||py>=this.c.height) continue;
      const sxp = sx + Math.min(sw-1, Math.floor(x*sw/dw));
      const syp = sy + Math.min(sh-1, Math.floor(y*sh/dh));
      const si = (syp*src.width+sxp)*4, di=(py*this.c.width+px)*4;
      this.c.data[di]=src.data[si]; this.c.data[di+1]=src.data[si+1];
      this.c.data[di+2]=src.data[si+2]; this.c.data[di+3]=src.data[si+3];
    }
  }
  getImageData(x,y,w,h){
    const out=new Uint8ClampedArray(w*h*4);
    for(let yy=0;yy<h;yy++)for(let xx=0;xx<w;xx++){
      const si=((y+yy)*this.c.width+(x+xx))*4, di=(yy*w+xx)*4;
      out[di]=this.c.data[si]; out[di+1]=this.c.data[si+1];
      out[di+2]=this.c.data[si+2]; out[di+3]=this.c.data[si+3];
    }
    return {data:out,width:w,height:h};
  }
  putImageData(img,x,y){
    for(let yy=0;yy<img.height;yy++)for(let xx=0;xx<img.width;xx++){
      const si=(yy*img.width+xx)*4, di=((y+yy)*this.c.width+(x+xx))*4;
      this.c.data[di]=img.data[si]; this.c.data[di+1]=img.data[si+1];
      this.c.data[di+2]=img.data[si+2]; this.c.data[di+3]=img.data[si+3];
    }
  }
  fillRect(){} fillStyle(){}
}
global.document = { createElement(){
  const c = {
    _w:0, _h:0, data:null, _ctx:null,
    get width(){ return this._w; },
    set width(v){ this._w = v|0; this.data = new Uint8ClampedArray(this._w*this._h*4); },
    get height(){ return this._h; },
    set height(v){ this._h = v|0; this.data = new Uint8ClampedArray(this._w*this._h*4); },
    getContext(){ if(!this._ctx) this._ctx=new Ctx(this); return this._ctx; },
  };
  return c;
} };
global.window = { innerHeight: 1600 };
global.performance = { now: () => Date.now() };
global.localStorage = { getItem(){return null}, setItem(){} };
global.speechSynthesis = { getVoices:()=>[], speak(){}, cancel(){}, pause(){}, resume(){}, speaking:false };
global.indexedDB = { open(){ return {}; } };
global.URL = { createObjectURL(){return ''}, revokeObjectURL(){} };
module.exports = {};
