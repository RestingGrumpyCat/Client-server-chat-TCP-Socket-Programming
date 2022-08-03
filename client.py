import socket
import os
import signal
import sys
import argparse
from urllib.parse import urlparse
import selectors

# Selector for helping us select incoming data from the server and messages typed in by the user.

sel = selectors.DefaultSelector()

# Socket for sending messages.

client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

# User name for tagging sent messages.

user = ''

#for filtering message with terms user is not following
follow_list = []
#flag for switching between receiving chat message and receiving file bytes
receive_file = False

# Signal handler for graceful exiting.  Let the server know when we're gone.

def signal_handler(sig, frame):
    print('Interrupt received, shutting down ...')
    message=f'DISCONNECT {user} CHAT/1.0\n'
    client_socket.send(message.encode())
    sys.exit(0)

# Simple function for setting up a prompt for the user.

def do_prompt(skip_line=False):
    if (skip_line):
        print("")
    print("> ", end='', flush=True)

# Read a single line (ending with \n) from a socket and return it.
# We will strip out any \r and \n in the process.

def get_line_from_socket(sock):

    done = False
    line = ''
    while (not done):
        char = sock.recv(1).decode()
        if (char == '\r'):
            pass
        elif (char == '\n'):
            done = True
        else:
            line = line + char
    return line


# Function to handle incoming messages from server.  Also look for disconnect messages to shutdown.

def handle_message_from_server(sock, mask):
    global file_size
    global file
    global file_origin
    global receive_file

    #if its receiving file mode
    if receive_file != False:
        #receive file byte and save to local file
        f = open(file, 'wb')
        if(file_size<2048):
            file_byte = sock.recv(file_size)
            f.write(file_byte)
        else:
            s = file_size
            while (s > 0):
                if (s < 2048):
                    file_byte = sock.recv(s)
                else:
                    file_byte = sock.recv(2048)
                    if not file_byte:
                        continue

                f.write(file_byte)
                s = s - 2048
        #tell server the transfer has completed
        forwarded_message = 'Successful file transfer!' + '\n'
        sock.send(forwarded_message.encode())
        #set back to receiving chat message mode
        receive_file = False

    else:
        message=get_line_from_socket(sock)
        words=message.split(' ')
        if words[0] == 'DISCONNECT':
            print('Disconnected from server ... exiting!')
            sys.exit(0)
        else:
            #remove the term user attempts to unfollow
            if 'No longer following' in message:
                follow_list.remove(words[3])
                print(message)
                do_prompt()
            #add the term user want to follow
            elif 'Now following' in message:
                follow_list.append(words[2])
                print(message)
                do_prompt()
            #this is a reply to !list, so print out active users now
            elif 'CMD' in message:
                message= message.replace('CMD', '')
                print(message)
                do_prompt()
            #print an error message
            elif 'ERROR' in message:
                print(message)
                do_prompt()
            #this means server is ready to receive file, client sends file to server
            elif 'Ready to receive file' in message:
                filename = words[4]
                file_size = int(words[6])
                f = open(filename, 'rb')
                s = file_size
                if(file_size < 2048):
                    file_byte = f.read(file_size)
                    sock.send(file_byte)
                else:
                    while(s > 0):
                        if(s < 2048):
                            file_byte = f.read(s)
                        else:
                            file_byte = f.read(2048)
                        sock.send(file_byte)
                        s = s - 2048
                print('Done sending to the server')
                do_prompt()
            #this means client is ready to receive file
            elif 'Content-Length:' in message and 'Incoming file' in message and 'Origin' in message:
                file_size = int(words[6])
                file = words[2]
                file_origin = words[4]
                print(message)
                forwarded_message = f'Ready to receive file {file} Content-Length: {file_size}' + '\n'
                sock.send(forwarded_message.encode())
                receive_file = True
                do_prompt()
            else:
                #print out message with tags in follow list
                for tag in follow_list:
                    if '@' in tag:
                        if tag in message:
                            print(message)
                            do_prompt()
                    else:
                        for seg in words:
                            if tag == seg:
                                print(message)
                                do_prompt()

# Function to handle incoming messages from user.

def handle_keyboard_input(file, mask):
    line=sys.stdin.readline()
    if '!attach' in line:
        words = line.split()
        if len(words) < 2:
            print('Invalid command format, please input the the name of the file to be distributed')
            do_prompt
        else:
            try:
                filename = words[1]
                size = os.path.getsize(filename)
                line = line.strip('\n')
                message= f"Incoming file: {filename} Origin: {user} Content-Length: {size} {line}" + '\n'
                client_socket.send(message.encode())
            except(FileNotFoundError):
                print('Error: file not found.')
            do_prompt
    elif '!exit' in line:
        print('Exiting ...')
        message = f'DISCONNECT {user} CHAT/1.0\n'
        client_socket.send(message.encode())
        sys.exit(0)
    else:
        message = f'@{user}: {line}'
        client_socket.send(message.encode())
        do_prompt()

# Our main function.

def main():

    global user
    global client_socket

    # Register our signal handler for shutting down.

    signal.signal(signal.SIGINT, signal_handler)

    # Check command line arguments to retrieve a URL.

    parser = argparse.ArgumentParser()
    parser.add_argument("user", help="user name for this user on the chat service")
    parser.add_argument("server", help="URL indicating server location in form of chat://host:port")
    args = parser.parse_args()


    # Check the URL passed in and make sure it's valid.  If so, keep track of
    # things for later.

    try:
        server_address = urlparse(args.server)
        if ((server_address.scheme != 'chat') or (server_address.port == None) or (server_address.hostname == None)):
            raise ValueError
        host = server_address.hostname
        port = server_address.port
    except ValueError:
        print('Error:  Invalid server.  Enter a URL of the form:  chat://host:port')
        sys.exit(1)
    user = args.user
    follow_list.append('@all')
    follow_list.append(f'@{user}')

    # Now we try to make a connection to the server.

    print('Connecting to server ...')
    try:
        client_socket.connect((host, port))
    except ConnectionRefusedError:
        print('Error:  That host or port is not accepting connections.')
        sys.exit(1)

    # The connection was successful, so we can prep and send a registration message.
    
    print('Connection to server established. Sending intro message...\n')
    message = f'REGISTER {user} CHAT/1.0\n'
    client_socket.send(message.encode())
   
    # Receive the response from the server and start taking a look at it

    response_line = get_line_from_socket(client_socket)
    response_list = response_line.split(' ')
        
    # If an error is returned from the server, we dump everything sent and
    # exit right away.
    if response_list[0] != '200':
        print('Error:  An error response was received from the server.  Details:\n')
        print(response_line)
        print('Exiting now ...')
        sys.exit(1)   
    else:
        print('Registration successful.  Ready for messaging!')

    # Set up our selector.

    client_socket.setblocking(True)
    sel.register(client_socket, selectors.EVENT_READ, handle_message_from_server)
    sel.register(sys.stdin, selectors.EVENT_READ, handle_keyboard_input)
    
    # Prompt the user before beginning.

    do_prompt()

    # Now do the selection.

    while(True):
        events = sel.select()
        for key, mask in events:
            callback = key.data
            callback(key.fileobj, mask)    



if __name__ == '__main__':
    main()
