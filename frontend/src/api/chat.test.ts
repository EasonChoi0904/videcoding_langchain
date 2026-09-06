import { describe, expect, test, vi } from 'vitest'
import { handleSseBlock, type AskEvents } from './chat'

// 屏蔽 http 实例依赖链(其引入 router → createWebHistory 依赖浏览器环境);
// SSE 解析纯函数本身不触发任何网络请求
vi.mock('./http', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}))

/** SSE 协议解析测试:问答流的四种事件 + 异常容错。 */

function makeEvents() {
  return {
    onCitations: vi.fn(),
    onToken: vi.fn(),
    onDone: vi.fn(),
    onError: vi.fn(),
  } as AskEvents
}

describe('SSE 报文解析(handleSseBlock)', () => {
  test('解析 citations 事件:携带引用片段与缓存标记', () => {
    const ev = makeEvents()
    const block = [
      'event: citations',
      'data: {"sources":[{"n":1,"doc_name":"表.xlsx","text":"小米15","score":0.95}],"cached":true}',
    ].join('\n')
    handleSseBlock(block, ev)
    expect(ev.onCitations).toHaveBeenCalledWith(
      [{ n: 1, doc_name: '表.xlsx', text: '小米15', score: 0.95 }],
      true,
    )
  })

  test('解析 token 事件:内容增量逐条回调', () => {
    const ev = makeEvents()
    handleSseBlock('event: token\ndata: {"delta":"电池"}', ev)
    expect(ev.onToken).toHaveBeenCalledWith('电池')
  })

  test('解析 done 事件:refused 标记与消息 id', () => {
    const ev = makeEvents()
    handleSseBlock(
      'event: done\ndata: {"message_id":"m1","conversation_id":3,"refused":true,"title":"标题"}',
      ev,
    )
    expect(ev.onDone).toHaveBeenCalledWith(
      expect.objectContaining({ message_id: 'm1', conversation_id: 3, refused: true, title: '标题' }),
    )
  })

  test('解析 error 事件:code 与 message', () => {
    const ev = makeEvents()
    handleSseBlock('event: error\ndata: {"code":"INTERNAL","message":"出错了"}', ev)
    expect(ev.onError).toHaveBeenCalledWith('INTERNAL', '出错了')
  })

  test('畸形 JSON 块被忽略且不影响其它回调', () => {
    const ev = makeEvents()
    handleSseBlock('event: token\ndata: {broken json', ev)
    expect(ev.onToken).not.toHaveBeenCalled()
    expect(ev.onError).not.toHaveBeenCalled()
  })

  test('非事件块(心跳/空行等)静默跳过', () => {
    const ev = makeEvents()
    handleSseBlock(': keep-alive', ev)
    handleSseBlock('random text', ev)
    expect(ev.onToken).not.toHaveBeenCalled()
    expect(ev.onError).not.toHaveBeenCalled()
  })

  test('done 事件缺字段时安全降级(refused 默认 false)', () => {
    const ev = makeEvents()
    handleSseBlock('event: done\ndata: {"message_id":"m2","conversation_id":9}', ev)
    expect(ev.onDone).toHaveBeenCalledWith(
      expect.objectContaining({ message_id: 'm2', refused: false }),
    )
  })
})
