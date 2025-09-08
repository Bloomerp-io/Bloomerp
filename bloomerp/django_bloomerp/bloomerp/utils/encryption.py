from cryptography.fernet import Fernet

class BloomerpEncryptionSuite:
    def __init__(self, key:str=None):
        '''Initializes the encryption suite'''
        self.key = key
        self.suite = Fernet(self.key)

    def encrypt_primary_key(self,pk):
        '''Encrypts a primary key integer, returns encrypted pk string'''
        encrypted = self.suite.encrypt(str(pk).encode())
        return encrypted.decode()

    def decrypt_primary_key(self,encrypted_pk):
        '''Decrypts an encrypted pk that is in a string format'''
        pk = self.suite.decrypt(encrypted_pk.encode())
        return int(pk.decode())