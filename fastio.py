import argparse
import os
import uuid
import shutil
import flask
from flask_socketio import SocketIO, emit
from urllib.parse import urlparse
import eventlet
eventlet.monkey_patch(all=False, socket=True)
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, send_file, make_response,request, jsonify
import hashlib
import mimetypes
import magic
import requests
from io import BytesIO
def get_mime_type(filename):
    # Try Python's built-in mimetypes module first
    mime_type, _ = mimetypes.guess_type(filename)
    
    if not mime_type:
        # If that fails, use python-magic
        with magic.Magic() as mag:
            mime_type = mag.from_file(filename)
            
    return mime_type
def find_drive_with_least_space(driveletters):
    drive_space = {}
    for letter in driveletters:
        total, used, free = shutil.disk_usage(f"{letter}:/")
        drive_space[letter] = free
    return min(drive_space, key=drive_space.get)

def save_file_to_drive(file, drive, param_id):
    filename = file.filename
    filename = filename.replace("_", "")

    file.save(f"{drive}:/files/{param_id}_{filename}")
def save_chunk_to_drive(chunk_data, drive, metadata_id, chunk_number):
    chunk_filename = os.path.join(f"{drive}:/bucket", f'{metadata_id}_{chunk_number}.dat')
    with open(chunk_filename, 'wb') as chunk_file:
        chunk_file.write(chunk_data)
   
def get_available_drives():
        drives = [f"{letter}" for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if os.path.exists(f"{letter}:/")]
        return drives
def find_file_by_id(driveletters, id):
    for letter in driveletters:
        folder_path = f"{letter}:/files/"
        if os.path.exists(folder_path):
            for filename in os.listdir(folder_path):
                if id in filename and not filename.endswith(".metadata"):
                    return os.path.join(folder_path, filename)
    return None

def main():
    parser = argparse.ArgumentParser(description='A file storage server to increase upload and download speeds.')

    # Define the command-line arguments
    parser.add_argument('-p', '--port', type=int, help='Specidffy the port',required=False)
    parser.add_argument('-d', '--driveletters', help='Specify the drive letters, if none was found it will find drives that have been noted by fastio as available for storage',required=False)
    parser.add_argument('-ps', '--password', help='Specify the password for the server, if not provided will default to admin. You can not change password using commands nor the web interface, you will have to change it in the config.ini file',required=False)
    parser.add_argument('-u', '--username', help='Specify the username for the server, if not provided will default to admin. You can not change username using commands nor the web interface, you will have to change it in the config.ini file',required=False)
    parser.add_argument('-i', '--ipaddress', help='Host the server on a custom ip address',required=False)
    parser.add_argument('-on', '--open', help='Open the server in the default web browser',required=False,type=bool)


    # Parse the command-line arguments
    args = parser.parse_args()
    
    if args.ipaddress:
        args.ip = args.ipaddress 
    else:
        args.ip = "127.0.0.1"


        

    if not args.port:
        args.port = 5000

    if not args.username:
        args.username = "admin"

    if not args.password:
        args.password = "admin"


    print("Starting server on port", args.port)

    if args.open:
        webbrowser.open(f"http://{args.ip}:{args.port}")


    #create a file in this directory to store the drive letters if they are not already there in the file
    if not os.path.exists("config.ini"):
         if not args.driveletters:
            print("Since config.ini file was not found, you need to specify the drive letters")
         
         with open("config.ini", "w") as f:

            f.write(f"DRIVES={args.driveletters}\nITEM_PER_PAGE=10\nENABLE_FILE_SPLITTING_ACROSS_DRIVES=True\nUSERNAME={args.username}\nPASSWORD={args.password}")

    
    if args.username == "admin" and args.password == "admin":
        print("Default username and password detected, please change it to a more secure password")
    #if username or password has been provided, add it to the config file without overwriting the current settings
    else:
        with open("config.ini", "r") as f:
            letters = f.read()
            letters = letters.split("\n")
            with open("config.ini", "w") as f:
                    f.write(f"DRIVES={letters[0].split('=')[1]}\nITEM_PER_PAGE={letters[1].split('=')[1]}\nENABLE_FILE_SPLITTING_ACROSS_DRIVES={letters[2].split('=')[1]}\nUSERNAME={args.username}\nPASSWORD={args.password}")

    
    

    with open("config.ini", "r") as f:
        letters = f.read()
        driveletters = letters.split("\n")
        driveletters = driveletters[0].split("=")[1]
        driveletters = driveletters.split(",")



        if not driveletters:
            print("No drive letters found in the file, please specify the drive letters")
            return
        for letter in driveletters:
            #create a called bucket and files directory for each drive letter
            if not os.path.exists(f"{letter}:/bucket"):
                os.mkdir(f"{letter}:/bucket")
            if not os.path.exists(f"{letter}:/files"):
                os.mkdir(f"{letter}:/files")


    print("Server started on port " + str(args.port) + " with the following drive letters: " + str(driveletters))
    
    app = flask.Flask(__name__)
    app.config ['SECRET_KEY'] = 'secret'
    app.config['DEBUG'] = True
    app.config['TEMPLATES_AUTO_RELOAD'] = True
    app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
    
    sio = SocketIO(app)




    
    @app.route('/upload', methods=['POST'])
    def upload():
            hidden = request.form['hidden']
            key = request.form['key']
            
            if 'file' in request.files:
                file = request.files['file']
                if file.filename == '':
                    return 'No file selected', 400
                content_length = request.content_length
               
                split_files = letters.split("\n")[2].split("=")[1]
                

                if split_files == "False":
                    least_space_drive = find_drive_with_least_space(driveletters)
                    metadata_id = str(uuid.uuid4())
                    save_file_to_drive(file, least_space_drive, metadata_id)
                    
                    return jsonify({'message': 'File uploaded', 'id': metadata_id}), 200
                                       
                elif split_files == "True":
                    chunk_size = content_length // 10

                    num_chunks = (content_length + chunk_size - 1) // chunk_size
                    sorted_drives = sorted(driveletters, key=lambda x: shutil.disk_usage(f"{x}:/").free, reverse=True)
                    metadata_id = str(uuid.uuid4())
                    saved_chunks = 0
                    emit('progress', {'progress': 0},namespace='/',broadcast=True)
                    for i in range(num_chunks):
                        chunk_data = file.read(chunk_size)
                        if not chunk_data:
                            break  # Break the loop if no more data is available

                        drive = sorted_drives[i % len(sorted_drives)]  # Use modulo to cycle through drives
                        save_chunk_to_drive(chunk_data, drive, metadata_id, i + 1)
                        saved_chunks += 1
                        
                        progress = (i + 1) / num_chunks
                       
                        emit('progress', {'progress': progress},namespace='/',broadcast=True)
             


                    metadata_filename = os.path.join(find_drive_with_least_space(driveletters) + ":/files", metadata_id + ".metadata")
                    size_in_mb = content_length / (1000000)

                    with open(metadata_filename, 'w') as metadata_file:
                        metadata_file.write(f'CHUNKS={saved_chunks}\n')
                        metadata_file.write(f'ORIGINALFILE={file.filename}\n')
                      
                        metadata_file.write(f'SIZE={size_in_mb}\n')
                        metadata_file.write(f'HIDDEN={hidden}\n')
                        if key:
                            metadata_file.write(f'KEY={key}\n')


                    emit('progress', {'progress': 100},namespace='/',broadcast=True)
                    return jsonify({'message': 'File uploaded', 'id': metadata_id}), 200
                
                else:
                    return 'Invalid value for ENABLE_FILE_SPLITTING_ACROSS_DRIVES', 500
                
            else:
                return 'No file selected', 400
    @app.route('/play', methods=['GET'])
    def play():
        return flask.render_template('play.html')
    
    @app.route('/uploadU', methods=['POST'])
    def uploadU():
                    hidden = request.form['hidden']
                    key = request.form['key']
        
                    url  = request.args.get('url') 
                    name = urlparse(url)
                    name = os.path.basename(name.path)
                    if name == '':
                        return 'We could not get the file name from the url, we suggest you download the file and upload it manually', 400
            
            
                   #save the file to the drive with the least space available and then use that file to split it across the drives
                    least_space_drive = find_drive_with_least_space(driveletters)
                    metadata_id = str(uuid.uuid4())
                    response = requests.get(url)
                    content_length = len(response.content)
                    split_files = letters.split("\n")[2].split("=")[1]
                    if split_files == "False":
                        with open(f"{least_space_drive}:/files/{metadata_id}_{name}", 'wb') as file:
                            file.write(response.content)
                        return jsonify({'message': 'File uploaded', 'id': metadata_id}), 200
                    elif split_files == "True":
                        chunk_size = content_length // 10
                        num_chunks = (content_length + chunk_size - 1) // chunk_size
                        sorted_drives = sorted(driveletters, key=lambda x: shutil.disk_usage(f"{x}:/").free, reverse=True)
                        saved_chunks = 0
                        emit('progress', {'progress': 0},namespace='/',broadcast=True)
                        for i in range(num_chunks):
                            chunk_data = response.content[i * chunk_size:(i + 1) * chunk_size]
                            if not chunk_data:
                                break  # Break the loop if no more data is available

                            drive = sorted_drives[i % len(sorted_drives)]  # Use modulo to cycle through drives
                            save_chunk_to_drive(chunk_data, drive, metadata_id, i + 1)
                            saved_chunks += 1
                            progress = (i + 1) / num_chunks
                            emit('progress', {'progress': progress},namespace='/',broadcast=True)
                        metadata_filename = os.path.join(find_drive_with_least_space(driveletters) + ":/files", metadata_id + ".metadata")
                        size_in_mb = content_length / (1000000)
                        with open(metadata_filename, 'w') as metadata_file:
                            metadata_file.write(f'CHUNKS={saved_chunks}\n')
                            metadata_file.write(f'ORIGINALFILE={name}\n')
                            metadata_file.write(f'SIZE={size_in_mb}\n')
                            metadata_file.write(f'HIDDEN={hidden}\n')
                        
                            if key != "null":
                                metadata_file.write(f'KEY={key}\n')
                        emit('progress', {'progress': 100},namespace='/',broadcast=True)
                        return jsonify({'message': 'File uploaded', 'id': metadata_id}), 200
                    else:
                        return 'Invalid value for ENABLE_FILE_SPLITTING_ACROSS_DRIVES', 500
                    
         
    
            
   
    @app.route('/download/<id>', methods=['GET','PROPFIND'])
    def download(id):
           
                        file_path = find_file_by_id(driveletters, id)
                       
                        if file_path:
                            with open(file_path, 'rb') as file:
                        
                                response = make_response(file.read())

                                original_file = file_path.split("_")[1]
                         
                                response.headers['Content-Disposition'] = f'inline; filename={original_file}'
                                response.headers['Content-Type'] =  get_mime_type(file_path)
                              
                                response.headers['Accept-Ranges'] = 'bytes'

                        



                                return response, 200, {'Content-Disposition': f'attachment; filename={original_file}'}
                        else:
                            
                            #search for metadata file in all drives
                            for letter in driveletters:
                                metadata_filename = f"{letter}:/files/{id}.metadata"
                                if os.path.exists(metadata_filename):
                                    break
                            else:
                                return 'File not found', 404
                            with open(metadata_filename, 'r') as metadata_file:
                                metadata = metadata_file.read()
                         
                            metadata = metadata.split("\n")
                            chunks = int(metadata[0].split("=")[1])
                
                            original_file = metadata[1].split("=")[1]
                         
                             #check if metadata has key=
                            if any("KEY=" in item for item in metadata):
                                return 'Key required', 401

                           
                            
                
                            #search for chunks in all drives then combine them and send the file
                            file_data = b''
                            for i in range(chunks):
                                for letter in driveletters:
                                    chunk_filename = f"{letter}:/bucket/{id}_{i + 1}.dat"
                            
                                    if os.path.exists(chunk_filename):
                                        break
                                else:
                                    return 'File not found', 404
                                with open(chunk_filename, 'rb') as chunk_file:
                                    with ThreadPoolExecutor() as executor:
                                        for data_chunk in iter(lambda: chunk_file.read(os.path.getsize(chunk_filename)), b''):
                                            file_data += data_chunk
                            response = make_response(file_data)
                         
                            response.headers['Content-Disposition'] = f'inline; filename={original_file}'
                            
                            response.headers['Content-Type'] =  get_mime_type(original_file)
                            response.headers['Accept-Ranges'] = 'bytes'

                

                          
                    
                            return response, 200, {'Content-Disposition': f'attachment; filename={original_file}'}
  
                        

    @app.route('/view/<id>', methods=['GET'])
    def view(id):
           
                        file_path = find_file_by_id(driveletters, id)
                   
                        if file_path:
                                file_size = os.path.getsize(file_path)
                                if file_size > 10 * 1024 * 1024:
                                
                                    return "Data too big to be displayed. Would you like to download it instead? <a href='/download/" + id + "'>Download</a> Or play it instead? if so go to <a href='/play'>Play</a> and enter the id of the file", 400
                                
                        if file_path:
                            with open(file_path, 'rb') as file:
                             
                                
                                
                                 
                        
                                response = make_response(file.read())

                                original_file = file_path.split("_")[1]
                    
                                response.headers['Content-Type'] =  get_mime_type(file_path)
                                response.headers['Accept-Ranges'] = 'bytes'
                            
                                return response
                        else:
                            
                            #search for metadata file in all drives
                            for letter in driveletters:
                                metadata_filename = f"{letter}:/files/{id}.metadata"
                                if os.path.exists(metadata_filename):
                                    break
                            else:
                                return 'File not found', 404
                            with open(metadata_filename, 'r') as metadata_file:
                                metadata = metadata_file.read()

                
                           
                           
                            
                            metadata = metadata.split("\n")
                            
                            chunks = int(metadata[0].split("=")[1])
                
                            original_file = metadata[1].split("=")[1]
                
                            if  any("KEY=" in item for item in metadata):

                                return 'Key required', 401

                            
                            
                       
                           
                
                            #search for chunks in all drives then combine them and send the file
                            file_data = b''
                            for i in range(chunks):
                                for letter in driveletters:
                                    chunk_filename = f"{letter}:/bucket/{id}_{i + 1}.dat"
                            
                                    if os.path.exists(chunk_filename):
                                        break
                                else:
                                    return 'File not found', 404
                                with open(chunk_filename, 'rb') as chunk_file:
                                    with ThreadPoolExecutor() as executor:
                                        for data_chunk in iter(lambda: chunk_file.read(os.path.getsize(chunk_filename)), b''):
                                            file_data += data_chunk

                            
                            #check if file is too big to be displayed
                            if len(file_data) > 10 * 1024 * 1024:
                            
                                return "Data too big to be displayed. Would you like to download it instead? <a href='/download/" + id + "'>Download</a> Or play it instead? if so go to <a href='/play'>Play</a> and enter the id of the file", 400
                            

                            response = make_response(file_data)

                            response.headers['Content-Type'] =  get_mime_type(original_file)

                            #if video file, use the video tag
                            if response.headers['Content-Type'].startswith('video'):
                                return flask.render_template('play.html', id=id)
                            response.headers['Accept-Ranges'] = 'bytes'


    

                            return response 

    @app.route('/view/<id>/<key>', methods=['GET'])
    def viewKey(id,key):
           
                        file_path = find_file_by_id(driveletters, id)
                   
                        if file_path:
                                file_size = os.path.getsize(file_path)
                                if file_size > 10 * 1024 * 1024:
                                    return "Data too big to be displayed. Would you like to download it instead? <a href='/download/" + id + "'>Download</a> Or play it instead? if so go to <a href='/play'>Play</a> and enter the id of the file", 400
                                
                        if file_path:
                            with open(file_path, 'rb') as file:
                             
                                
                                
                                 
                        
                                response = make_response(file.read())

                                original_file = file_path.split("_")[1]
                    
                                response.headers['Content-Type'] =  get_mime_type(file_path)
                                response.headers['Accept-Ranges'] = 'bytes'
                            
                                return response
                        else:
                            
                            #search for metadata file in all drives
                            for letter in driveletters:
                                metadata_filename = f"{letter}:/files/{id}.metadata"
                                if os.path.exists(metadata_filename):
                                    break
                            else:
                                return 'File not found', 404
                            with open(metadata_filename, 'r') as metadata_file:
                                metadata = metadata_file.read()

                
                           
                           
                            
                            metadata = metadata.split("\n")
                            
                            chunks = int(metadata[0].split("=")[1])
                
                            original_file = metadata[1].split("=")[1]
                            if any("KEY=" in item for item in metadata):

                                if metadata[4].split("=")[1] != key:
                                    return "Invalid key", 401
                                

                            
                            
                       
                           
                
                            #search for chunks in all drives then combine them and send the file
                            file_data = b''
                            for i in range(chunks):
                                for letter in driveletters:
                                    chunk_filename = f"{letter}:/bucket/{id}_{i + 1}.dat"
                            
                                    if os.path.exists(chunk_filename):
                                        break
                                else:
                                    return 'File not found', 404
                                with open(chunk_filename, 'rb') as chunk_file:
                                    with ThreadPoolExecutor() as executor:
                                        for data_chunk in iter(lambda: chunk_file.read(os.path.getsize(chunk_filename)), b''):
                                            file_data += data_chunk
                            
                            #check if file is too big to be displayed
                            if len(file_data) > 10 * 1024 * 1024:
                                return "Data too big to be displayed. Would you like to download it instead? <a href='/download/" + id + "'>Download</a> Or play it instead? if so go to <a href='/play'>Play</a> and enter the id of the file", 400
                            
                            response = make_response(file_data)

                            response.headers['Content-Type'] =  get_mime_type(original_file)
                            response.headers['Accept-Ranges'] = 'bytes'

                            return response
                        
    @app.route('/download/<id>/<key>', methods=['GET'])
    def downloadKey(id,key):
           
                        file_path = find_file_by_id(driveletters, id)
                       
                        if file_path:
                            with open(file_path, 'rb') as file:
                        
                                response = make_response(file.read())

                                original_file = file_path.split("_")[1]
                         
                                response.headers['Content-Disposition'] = f'inline; filename={original_file}'
                                response.headers['Content-Type'] =  get_mime_type(file_path)
                              
                                response.headers['Accept-Ranges'] = 'bytes'

                        



                                return response, 200, {'Content-Disposition': f'attachment; filename={original_file}'}
                        else:
                            
                            #search for metadata file in all drives
                            for letter in driveletters:
                                metadata_filename = f"{letter}:/files/{id}.metadata"
                                if os.path.exists(metadata_filename):
                                    break
                            else:
                                return 'File not found', 404
                            with open(metadata_filename, 'r') as metadata_file:
                                metadata = metadata_file.read()
                         
                            metadata = metadata.split("\n")
                            chunks = int(metadata[0].split("=")[1])
                
                            original_file = metadata[1].split("=")[1]
                       
                            if not any("KEY=" in item for item in metadata):
                          
                                if metadata[4].split("=")[1] != key:
                                    return "Invalid key", 401
                                

                           
                            
                
                            #search for chunks in all drives then combine them and send the file
                            file_data = b''
                            for i in range(chunks):
                                for letter in driveletters:
                                    chunk_filename = f"{letter}:/bucket/{id}_{i + 1}.dat"
                            
                                    if os.path.exists(chunk_filename):
                                        break
                                else:
                                    return 'File not found', 404
                                with open(chunk_filename, 'rb') as chunk_file:
                                    with ThreadPoolExecutor() as executor:
                                        for data_chunk in iter(lambda: chunk_file.read(os.path.getsize(chunk_filename)), b''):
                                            file_data += data_chunk
                            response = make_response(file_data)
                         
                            response.headers['Content-Disposition'] = f'inline; filename={original_file}'
                            
                            response.headers['Content-Type'] =  get_mime_type(original_file)
                            response.headers['Accept-Ranges'] = 'bytes'

                            

                          
                    
                            return response, 200, {'Content-Disposition': f'attachment ; filename={original_file}'}
                        
    #
                        
                        

                    
    @app.route('/list/<page>', methods=['GET'])
    def list_files(page):
                    files_per_page = []

                    items_per_page = int(letters.split("\n")[1].split("=")[1])

                    start_index = (int(page) - 1) * items_per_page
                    end_index = start_index + items_per_page

                    for letter in driveletters:
                      
                             
                            for file in os.listdir(f"{letter}:/files"):
                             
                                    
                             if file.endswith(".metadata"):
                                    with open(f"{letter}:/files/{file}", 'r') as metadata_file:
                                        metadata = metadata_file.read()
                                    metadata = metadata.split("\n")
                                    filename = metadata[1].split("=")[1]
                           
                                    size = float(metadata[2].split("=")[1])
                                    file_parts = filename.split('.')
                                    file_name = '.'.join(file_parts[:-1])  # Extracting name part
                                    file_type = file_parts[-1]  # Extracting type part
                                  
                                    if "HIDDEN=true" in metadata:
                                         continue   

                                    files_per_page.append({'id': file.split(".")[0],
                                                        'name': file_name,
                                                        'type': file_type,
                                                        'size': size})
                             else:
                                 size = os.path.getsize(f"{letter}:/files/{file}") / 1000000
                                 file_parts = file.split('_')
                                 file_name = file_parts[1]

                                 file_type = file_name.split('.')[-1]
                                 files_per_page.append({'id': file.split("_")[0],
                                                        'name': file_name.split('.')[0],
                                                        'type': file_type,
                                                        'size': size})

                    # Slice the list to include only the files for the current page
                    paginated_files = files_per_page[start_index:end_index]

                    return jsonify(paginated_files), 200

    
    
    @app.route('/delete/<id>', methods=['DELETE'])
    def delete(id):
                       
                        for letter in driveletters:
                            file_path = find_file_by_id(driveletters, id)
                            if file_path:
                                os.remove(file_path)
                                return 'File deleted', 200
                            metadata_filename = f"{letter}:/files/{id}.metadata"
                            if os.path.exists(metadata_filename):
                                break
                        else:
                            return 'File not found', 404
                        with open(metadata_filename, 'r') as metadata_file:
                            metadata = metadata_file.read()
                        metadata = metadata.split("\n")
                        chunks = int(metadata[0].split("=")[1])
            
                        for i in range(chunks):
                            for letter in driveletters:
                                chunk_filename = f"{letter}:/bucket/{id}_{i + 1}.dat"
                                if os.path.exists(chunk_filename):
                                    os.remove(chunk_filename)
                        for letter in driveletters:
                            metadata_filename = f"{letter}:/files/{id}.metadata"
                            if os.path.exists(metadata_filename):
                                os.remove(metadata_filename)
                        return 'File deleted', 200
    @app.route('/update', methods=['PUT'])
    def update():
                data = request.get_json()
                items_per_page = data['items_per_page']
                split_files = data['split_files']
                username = letters.split("\n")[3].split("=")[1]
                password = letters.split("\n")[4].split("=")[1]

      
                drives =''
                for index, item in enumerate(data['drives']):
                    if index != 0:  # Add comma after the first item
                        drives += ','
                    drives += item

        

                    
       
                
                with open("config.ini", "w") as f:
                    f.write(f"DRIVES={drives}\nITEM_PER_PAGE={items_per_page}\nENABLE_FILE_SPLITTING_ACROSS_DRIVES={split_files}\nUSERNAME={username}\nPASSWORD={password}")
                return 'Settings updated', 200
    

    @app.route('/', methods=['GET'])
    def dashboard():
                #get current list per page
                items_per_page = int(letters.split("\n")[1].split("=")[1])
                username = letters.split("\n")[3].split("=")[1]
                password = letters.split("\n")[4].split("=")[1]
                encrypted_password = hashlib.sha256(password.encode()).hexdigest()





                return flask.render_template('dashboard.html', items_per_page=items_per_page, port=args.port,driveletters=driveletters,available_drives=[drive for drive in get_available_drives() if drive not in driveletters],split_files=letters.split("\n")[2].split("=")[1].lower(),username=username,password=encrypted_password)
                
    

 
    
    
                    

    sio.run(app, host=args.ip, port=args.port)
    
                

                        

    




if __name__ == "__main__":
    main()
