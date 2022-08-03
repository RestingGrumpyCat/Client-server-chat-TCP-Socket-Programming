import socket
import os
import signal
import sys
import selectors
from os import path


# Selector for helping us select incoming data and connections from multiple sources.
from time import sleep

sel = selectors.DefaultSelector()

# Client list for mapping connected clients to their connections.
client_list = []
# follow dictionary for mapping each user to a list of people they are following
follow_dict = {}
#the list for users who will receive the shared file
file_sharing_list = []
#flag for switching between receiving chat message and receiving file bytes
receive_file = False
#file stats
file_size = 0
file = ''
file_origin = ''
# Signal handler for graceful exiting.  We let clients know in the process so they can disconnect too.

def signal_handler(sig, frame):
    print('Interrupt received, shutting down ...')
    message='DISCONNECT CHAT/1.0\n'
    for reg in client_list:
        reg[1].send(message.encode())
    sys.exit(0)

# Read a single line (ending with \n) from a socket and return it.
# We will strip out the \r and the \n in the process.

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

# Search the client list for a particular user.

def client_search(user):
    for reg in client_list:
        if reg[0] == user:
            return reg[1]
    return None

# Search the client list for a particular user by their socket.
def client_search_by_socket(sock):
    for reg in client_list:
        if reg[1] == sock:
            return reg[0]
    return None

# Add a user to the client list.
def client_add(user, conn):
    registration = (user, conn)
    client_list.append(registration)

# Remove a client when disconnected.
def client_remove(user):
    for reg in client_list:
        if reg[0] == user:
            client_list.remove(reg)
            break

#add @all and @username follow list by default
def follow_list_init(user):
    follow_list = []
    follow_list.append('@all')
    follow_list.append(f'@{user}')
    follow_dict[user] = follow_list

# Function to read messages from clients.

def read_message(sock, mask):
    global file_size
    global file
    global file_origin
    global receive_file
    global file_byte

    if receive_file == False:
        message = get_line_from_socket(sock)
        #if no msg is received, the connection is dead
        if message == '':
            print('Closing connection')
            sel.unregister(sock)
            sock.close()

        # Receive the message.
        else:
            user = client_search_by_socket(sock)
            words = message.split(' ')

            # Check for client disconnections.
            if words[0] == 'DISCONNECT':
                print(f'Received message from user {user}:  ' + message)
                print('Disconnecting user ' + user)
                client_remove(user)
                sel.unregister(sock)
                sock.close()
            #when user types !list, send to client the active users in client_list
            elif words[1] == '!list':
                active_users = []
                for reg in client_list:
                    active_users.append(reg[0])
                forwarded_message = ','.join(active_users) + '\n'
                forwarded_message = 'CMD' + forwarded_message
                sock.send(forwarded_message.encode())
            #when user uses !follow, add a new term to the follow list, only supports one term one command
            elif words[1] == '!follow':
                if len(words) >= 3:
                    will_follow = words[2]
                    if will_follow != '':
                        if will_follow not in follow_dict[user]:
                            follow_dict[user].append(will_follow)
                            forwarded_message = f'Now following {will_follow}' + '\n'
                            sock.send(forwarded_message.encode())
                        else:
                            #print error message if attempt to follow an exsiting tag
                            forwarded_message = 'ERROR : you are already following this tag' + '\n'
                            sock.send(forwarded_message.encode())
                else:
                    #make sure the command format is correct
                    forwarded_message = 'ERROR: invalid command format' + '\n'
                    sock.send(forwarded_message.encode())

            elif words[1] == '!unfollow':
                if len(words) >= 3:
                    stop_follow = words[2]
                    if stop_follow != '':
                        if stop_follow != '@all' and stop_follow != '@'+ user:
                            if stop_follow in follow_dict[user]:
                                follow_dict[user].remove(stop_follow)
                                forwarded_message = f'No longer following {stop_follow}' + '\n'
                                sock.send(forwarded_message.encode())
                            else:
                                #cant unfollow a term user is not already following
                                forwarded_message = 'ERROR: illegal attempt to unfollow since you are not following this tag' + '\n'
                                sock.send(forwarded_message.encode())
                        else:
                            #cant unfollow @all and @user
                            forwarded_message = f'ERROR: illegal attempt to unfollow @all or @{user}' + '\n'
                            sock.send(forwarded_message.encode())
                else:
                    #make sure the command format is correct
                    forwarded_message = 'ERROR: invalid command format' + '\n'
                    sock.send(forwarded_message.encode())
            #if users uses !follow?, print out terms user is currently following
            elif words[1] == '!follow?':
                forwarded_message = ','.join(follow_dict[user]) + '\n'
                forwarded_message = 'CMD' + forwarded_message
                sock.send(forwarded_message.encode())

            #when client attempts to send a file, server prepares to receive the file
            elif 'Content-Length:' in message and 'Incoming file' in message and 'Origin' in message:
                pos = message.find('!attach')
                seg = message[pos:].split()
                file_sharing_list.append(f'@{user}')
                for elem in seg:
                    if elem != '!attach':
                        file_sharing_list.append(elem)
                file_size = int(words[6])
                file = words[2]
                file_origin = words[4]
                # set receive_file to True to switch to file reading mode
                receive_file = True
                forwarded_message = f'Ready to receive file {file} Content-Length: {file_size}' + '\n'
                sock.send(forwarded_message.encode())

            #this means the client is ready to receive file, so server can send file
            elif 'Ready to receive file' in message:
                for tag in file_sharing_list:
                    #share the file with everyone who is following file sender or given terms
                    if follow_dict[user].count(tag) > 0:
                        connection = client_search(user)
                        f = open(file, 'rb')
                        s = file_size
                        if(file_size<2048):
                            file_byte = f.read(file_size)
                            connection.send(file_byte)
                        else:
                            while (s > 0):
                                if (s < 2048):
                                    file_byte = f.read(s)
                                else:
                                    file_byte = f.read(2048)
                                connection.send(file_byte)
                                s = s - 2048
                        print(f'{file_origin} sending file to {user}')
            #this means the client has successfully received the file
            elif 'Successful file transfer!' in message:
                #clear file sharing list for next transfer
                file_sharing_list.clear()
                print(message)

            # Send message to all users.  Send at most only once, and don't send to yourself.
            # Need to re-add stripped newlines here.
            else:
                print(f'Received message from user {user}:  ' + message)
                for reg in client_list:
                    if reg[0] == user:
                        continue
                    client_sock = reg[1]
                    forwarded_message = f'{message}\n'
                    client_sock.send(forwarded_message.encode())
    else:
        # when server is ready to receive file
        f = open(file, 'wb')
        s = file_size
        if(file_size < 2048):
            file_byte = sock.recv(file_size)
            f.write(file_byte)
        else:
            while (s > 0 ):
                if (s < 2048):
                    file_byte = sock.recv(s)
                else:
                    file_byte = sock.recv(2048)
                    if not file_byte:
                        continue

                f.write(file_byte)
                s = s - 2048

        print(f"Done receiving file from {file_origin}")
        msg = f"Incoming file: {file} Origin: {file_origin} Content-Length: {file_size}" + '\n'
        #send file information to clients who are going to receive the file
        for elem in follow_dict:
            if elem != file_origin:
                for tag in file_sharing_list:
                    if follow_dict[elem].count(tag) > 0:
                        connection = client_search(elem)
                        connection.send(msg.encode())

        #switch back to reiceiving chat messaging
        receive_file = False




# Function to accept and set up clients.

def accept_client(sock, mask):
    conn, addr = sock.accept()
    print('Accepted connection from client address:', addr)
    message = get_line_from_socket(conn)
    message_parts = message.split()

    # Check format of request.

    if ((len(message_parts) != 3) or (message_parts[0] != 'REGISTER') or (message_parts[2] != 'CHAT/1.0')):
        print('Error:  Invalid registration message.')
        print('Received: ' + message)
        print('Connection closing ...')
        response='400 Invalid registration\n'
        conn.send(response.encode())
        conn.close()
    elif (message_parts[1] == 'all'):
        print('Error:  Invalid registration message.')
        print('Connection closing ...')
        response = '400 Invalid registration\n'
        conn.send(response.encode())
        conn.close()

    # If request is properly formatted and user not already listed, go ahead with registration.

    else:
        user = message_parts[1]
        if (client_search(user) == None):
            client_add(user,conn)
            print(f'Connection to client established, waiting to receive messages from user \'{user}\'...')
            response='200 Registration successful\n'
            conn.send(response.encode())
            follow_list_init(user)
            conn.setblocking(True)
            sel.register(conn, selectors.EVENT_READ, read_message)

        # If user already in list , return a registration error.
        else:
            print('Error:  Client already registered.')
            print('Connection closing ...')
            response='401 Client already registered\n'
            conn.send(response.encode())
            conn.close()


# Our main function.

def main():

    # Register our signal handler for shutting down.

    signal.signal(signal.SIGINT, signal_handler)

    # Create the socket.  We will ask this to work on any interface and to pick
    # a free port at random.  We'll print this out for clients to use.

    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.bind(('', 0))
    print('Will wait for client connections at port ' + str(server_socket.getsockname()[1]))
    server_socket.listen(100)
    server_socket.setblocking(True)
    sel.register(server_socket, selectors.EVENT_READ, accept_client)
    print('Waiting for incoming client connections ...')
     
    # Keep the server running forever, waiting for connections or messages.
    
    while(True):
        events = sel.select()
        for key, mask in events:
            callback = key.data
            callback(key.fileobj, mask)    

if __name__ == '__main__':
    main()

