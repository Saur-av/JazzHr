import requests
import csv
import os
from typing import Dict
from dataclasses import dataclass
from selenium import webdriver
from time import sleep
from datetime import datetime


EMAIL = ""
PASSWORD = ""
FILE_NAME = "Locations.csv"

@dataclass
class Job:
    title : str
    id : int
    postal : str

def updateToCreate(json_obj : dict,locationFrame : list[str]) -> dict:
    ''':json_obj: :- Bascially a dictionary item.
    :locaionFrame: :- List With ['usState','usCity','usPostalCode']'''
    json_obj["city"] =  locationFrame[1]
    json_obj["state"] =  locationFrame[0]
    json_obj["postal"] =  locationFrame[2]
    json_obj["status"] = "Open"
    json_obj["dateOpened"] = datetime.today().strftime('%Y-%m-%d')
    json_obj["updatedAt"] = datetime.today().strftime('%Y-%m-%d')

    return json_obj

def updateToClose(json_obj : dict) -> Dict[str, str]:
    json_obj['status'] = 'Closed'
    return json_obj

class Automation:
    def __init__(self):
        self.req = requests.Session()
        self.driver = webdriver.Chrome()
        self.driver.implicitly_wait(10)
        self.driver.maximize_window()

        self.accountList : list[dict] = []
        self.activeAccId : int | None = None
        self.activeAccName : str = ""
        self.jobList : list[Job] = []
        self.jobDetails : list[dict] = []
        self.zipCodes = []

    def apiGet(self,url : str,params : dict | None = None) -> dict | None:
        self.updateCookies()
        
        res = self.req.get(url,params=params)
        
        if res.ok:
            return res.json()
        
        print(f"\nResponse Code : {res.status_code}\nError Message : {res.text}")

        res.raise_for_status()

    def authenticate(self):
        '''Authenticate the user with the credentials provided.'''
        self.driver.get("https://app.jazz.co/app/v2/login")
        self.driver.find_element("css selector","#email").send_keys(EMAIL)
        self.driver.find_element("css selector","#password").send_keys(PASSWORD)
        
        while "login" in self.driver.current_url:
            if input("Please Login and Press Enter...") == "#":
                break

        self.accountList = self.apiGet("https://api.jazz.co/customerManager/hub/accounts?page=1&per_page=100")
   
    def updateCookies(self):
        '''Update the session cookies with the cookies from the selenium driver.'''
        cookies = self.driver.get_cookies()

        for cookie in cookies:
            self.req.cookies.set(cookie['name'], cookie['value'])

    def selectUser(self) -> bool:
        '''Select the user account to work on, Returns True if the account was selected successfully, False otherwise.'''
        if not self.accountList:
            print("There were no user accounts found!")
            return False
        
        l = len(self.accountList)
        
        if self.activeAccId:
            self.driver.get("https://app.jazz.co/app/v2/portal/exit?type=linked") # Exit the current account

        print("Let's Select an user!")
        for index,account in self.accountList:
            print(f"{index} : {account['name']}")
        
        while True:
            selection = input("Please select the account you want to work on, Donot Choose an Closed Account: ")
            if selection.isdigit():
                selection = int(selection)
                if selection > 0 and selection < l:
                    self.chooseAccount(selection)
                    print(f"\n Selected Account: {self.activeAccName}")
                    return True
            print(f"Invalid Choice, Please choose [0 to {l-1}]")
    
    def chooseAccount(self,index):
        if index > 0 and index < len(self.accountList):
            raise IndexError("Index out of range!")
        
        if self.activeAccId:
            self.driver.get("https://app.jazz.co/app/v2/portal/exit?type=linked") # Exit the current account
        
        id = self.accountList[index]['id']
        self.driver.get(f"https://app.jazz.co/app/v2/dashboard?cid={id}")
        
        self.activeAccId = self.accountList[index]['id']
        self.activeAccName = self.accountList[index]['name']

        print(f"\n Selected Account: {self.activeAccName}")

    def updateJobs(self):
        self.updateCookies()

        permissions = self.apiGet("https://api.jazz.co/user/me?expand=customer%2Ccustomer.groups%2Ccustomer.plan%2Ccustomer.settings%2Ccustomer.timeZone%2Ccustomer.brand%2CmasterUser%2CpartnerRole%2Crole")
        id = permissions['id']

        jobs = self.apiGet(f"https://api.jazz.co/user/{id}/job/open?per_page=500")

        for j in jobs:
            self.jobList.append(Job(j['title'], j['id'], j['postal'].zfill(5)))
        
    def enrichJobDetails(self):
        self.updateCookies()
        
        for link in self.jobList:
            sleep(1)
            id = link.id

            self.jobDetails.append(self.apiGet(f"https://api.jazz.co/job/{id}?expand=hiringLead%2Cquestionnaire%2Cworkflow%2Cworkflow.workflowSteps%2CsyndicationChannels%2ChasScorecardTemplateJob"))

    def readCsv(self):
        #Updates all of the Zip Codes from the "Locations.csv" file.
        self.zipCodes = []
        if not os.path.exists(FILE_NAME):
            raise FileNotFoundError(f"File {FILE_NAME},Not Found!")
        
        with open(FILE_NAME, newline='') as csvfile:
            reader = csv.reader(csvfile)
            for row in reader:
                self.zipCodes.append(row)

    def getNext(self,target_zip):
        #Looks for the postal code and returns the Next Postal code to be updated.
        if isinstance(target_zip,tuple):
            target_zip = target_zip[0]

        target_zip = target_zip.zfill(5)

        for i, row in enumerate(self.zipCodes):
            if target_zip in row:
                next_index = (i + 1) % len(self.zipCodes)  # Wrap around to the beginning if end of list is reached
                if next_index == 1:
                    next_index = 2 # Skip the header row
                return self.zipCodes[next_index]
        print(f"Target zip code not found in the list. {target_zip} is not in the Locations.csv file.")
        return None

    def clone(self):
        '''Check for the Open Jobs in the SubAccount.
        Tries to Close the Job Posting.
        Then Tries to Clone Job Posting with the next Location.
        '''
        for job in self.jobDetails:

            postal = job['postal']
            if isinstance(postal,tuple):
                postal = postal[0]

            location = self.getNext(postal)

            if not location:
                print(f"It appears {job['id']} | {job['title']} is not in the {FILE_NAME}! Skipping...")
                continue
            
            #Close the job
            payload = updateToClose(job)
            apiUrl = "https://api.jazz.co/job?expand=syndicationChannels%2ChiringLead"
            req = self.req.put(apiUrl, json=payload)

            if req.ok:
                print(f"Closed {job['title']} | {job['id']}!")
            else:
                print(f"Failed to close a job, \n Job Id : {payload['id']}\nError : {req.status_code}\nMessage : {req.text}")
            sleep(2)

            #Clone the job
            payload = updateToCreate(job,location)
            apiUrl = f"https://api.jazz.co/job?isCloning=true&oldJobId={job["id"]}&expand=classifications%2ChiringLead%2Cquestionnaire%2Cquestionnaire.questions%2Cworkflow%2Cworkflow.workflowSteps%2Cworkflow.automatedReply"
            req = self.req.post(apiUrl,json=payload)

            if not req.ok:
                print(f"Failed to clone the job! \n Job Id : {payload['id']}\nError : {req.status_code}\nMessage : {req.text}")
                continue
            
            #Opening the Job
            data_payload = req.json()
            req = self.req.put(f"https://api.jazz.co/job/field", json={"customFieldValues": [], "id": data_payload['id']})
            
            new_job_id = req.json()['id']

            if req.ok:
                    print(f"Successfully Cloned the job.  {new_job_id} | {job['title']}!")
            else:
                print(f"Failed to Open the Cloned the job! \n Job Id : {new_job_id}\nError : {req.status_code}\nMessage : {req.text}")
            return

    def shutdown(self):
        '''Shutdown the browser.'''
        self.driver.quit()
        self.req.close()

if not os.path.exists(FILE_NAME):
    raise FileNotFoundError(f"The Config File {FILE_NAME} was not Found! Please Set the Correct Path in the Script.")

jazz = Automation()
jazz.authenticate()

def menu():
    if jazz.selected_account is not None:
        print(f"Selected Account: {jazz.activeAccName}\n\n")
    msg = f"""
"Welcome to JazzHR Automation Script!
    1. Run Main Automation [Scrape Jobs/Close Jobs/Open Jobs].
    2. Select User.
    3. Get Job Details.
    4. Clone Jobs.
    5. Exit
    """
    print(msg)

def main():
    while True:
        os.system('cls')
        menu()
        choice = input("Please select an option: ")
        if choice == "1":
            for index in range(len(jazz.accountList)):
                jazz.chooseAccount(index)
                jazz.updateJobs()
                jazz.enrichJobDetails()
                jazz.clone()
        elif choice == "2":
            jazz.selectUser()
        elif choice == "3":
            jazz.updateJobs()
            jazz.enrichJobDetails()
        elif choice == "4":
            jazz.clone()
        elif choice == "5":
            jazz.shutdown()
            exit()

try:
    main()
except:
    jazz.shutdown()