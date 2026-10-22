// Independent Minecraft implementation used only by the Python integration test.
const readline = require('readline')
const path = require('path')
const root = path.resolve(__dirname, '../../..')
const mineflayer = require(path.join(root, 'multiplayer-tests/node_modules/mineflayer'))
const emit = event => process.stdout.write(JSON.stringify(event) + '\n')
const bots = process.argv.slice(2).map((port, index) => {
  const bot = mineflayer.createBot({host:'127.0.0.1', port:Number(port),
    username:'ChatTest' + index, auth:'offline', version:'1.21.8', hideErrors:true})
  bot.once('spawn', () => emit({type:'spawn', index}))
  bot.on('messagestr', text => emit({type:'message', index, text}))
  bot.on('error', error => emit({type:'error', index, error:error.message}))
  bot.on('kicked', reason => emit({type:'kicked', index, reason}))
  return bot
})
readline.createInterface({input:process.stdin}).on('line', line => {
  const cmd = JSON.parse(line)
  if (cmd.op === 'chat') bots[cmd.index].chat(cmd.text)
  if (cmd.op === 'close') {
    bots.forEach(bot => bot.quit())
    setTimeout(() => process.exit(0), 250)
  }
})
