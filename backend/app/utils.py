import srt

def read_srt(content):        
    subtitles = list(srt.parse(content))
    
    subs = [sub.content for sub in subtitles]
    return "\n".join(subs)        