"""Deterministic Responses SSE bodies for local compatibility tests."""
import json


def stream(turn, *, name=None, arguments=None, text='finished', status='completed'):
    conflicting=status=='conflicting'
    if conflicting:status='completed'
    response={'id':f'resp_{turn}','object':'response','created_at':1,'model':'fixture',
              'status':'in_progress','background':False,'output':[],
              'usage':None,'incomplete_details':None,'error':None,'moderation':None}
    events=[{'type':'response.created','response':dict(response)}]
    if name:
        item={'type':'function_call','id':f'fc_{turn}','call_id':f'call_{turn}',
              'name':name,'arguments':'','status':'in_progress'}
        events.append({'type':'response.output_item.added','output_index':0,'item':dict(item)})
        events.append({'type':'response.function_call_arguments.delta','output_index':0,'item_id':item['id'],'delta':json.dumps(arguments)})
        item.update(arguments=json.dumps(arguments),status='completed')
        events.append({'type':'response.function_call_arguments.done','output_index':0,'item_id':item['id'],'arguments':item['arguments']})
    else:
        item={'type':'message','id':f'msg_{turn}','role':'assistant','status':'in_progress','content':[]}
        events.append({'type':'response.output_item.added','output_index':0,'item':dict(item)})
        events.append({'type':'response.output_text.delta','output_index':0,'content_index':0,'item_id':item['id'],'delta':text,'logprobs':[]})
        events.append({'type':'response.output_text.done','output_index':0,'content_index':0,'item_id':item['id'],'text':text,'logprobs':[]})
        item.update(status='completed',content=[{'type':'output_text','text':text,'annotations':[],'logprobs':[]}])
    events.append({'type':'response.output_item.done','output_index':0,'item':item})
    if status!='missing':
        response.update(status=status,output=[item],usage={'input_tokens':10,'output_tokens':5,'total_tokens':15})
        if status=='incomplete':response['incomplete_details']={'reason':'max_output_tokens'}
        if status=='failed':response['error']={'code':'server_error','message':'fixture failure'}
        events.append({'type':'response.'+status,'response':response})
    if conflicting:
        events.append({'type':'response.failed','response':dict(response,status='failed',error={'code':'server_error','message':'conflicting terminal'})})
    for index,event in enumerate(events):event['sequence_number']=index
    return ''.join('event: '+event['type']+'\ndata: '+json.dumps(event)+'\n\n' for event in events).encode()
